from __future__ import annotations

import hashlib
import hmac
import importlib

import jwt
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import service
from .config import Settings
from .models import Base, Mou
from .schemas import MouCreate, UgpassEvent
from .service import WorkflowError
from .upstream import UgpassClient, UpstreamUnavailable

PROBLEM = "application/problem+json"


def _problem(status: int, title: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"type": "about:blank", "title": title, "status": status, "detail": detail},
                        status_code=status, media_type=PROBLEM)


def load_client(dotted: str) -> UgpassClient:
    module, _, name = dotted.rpartition(".")
    if not module:
        raise ValueError(f"client_impl must be a dotted path, got {dotted!r}")
    client = getattr(importlib.import_module(module), name)()
    if not isinstance(client, UgpassClient):
        raise TypeError(f"{dotted} does not implement UgpassClient")
    return client


def verify_callback(secret: str, raw_body: bytes, signature: str | None) -> bool:
    """ASSUMED scheme: hex HMAC-SHA256 of the raw body. Replace once UGPass's real one is known."""
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def mou_view(m: Mou, base_url: str) -> dict:
    return {
        "mouId": m.id, "reference": m.reference, "documentHashSha256": m.document_hash, "status": m.status,
        "signatories": [{"name": s.name, "role": s.role, "organisation": s.organisation, "order": s.order,
                         "sealRequired": s.seal_required, "status": s.status} for s in m.signatories],
        "verificationUrl": f"{base_url.rstrip('/')}/api/v1/mous/{m.id}/verification",
    }


def create_app(settings: Settings | None = None, client: UgpassClient | None = None) -> FastAPI:
    settings = settings or Settings()
    client = client or load_client(settings.client_impl)
    kwargs = {}
    if settings.database_url.startswith("sqlite") and ":memory:" in settings.database_url:
        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    engine = create_engine(settings.database_url, **kwargs)
    if settings.create_tables:
        Base.metadata.create_all(engine)  # dev/tests only; production uses Alembic (see README)
    Session_ = sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(title="RPCMS UGPass signing adapter", version="0.1.0")

    def db():
        with Session_() as s:
            yield s

    def claims(authorization: str | None = Header(default=None)) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise WorkflowError(401, "Missing bearer token")
        try:
            c = jwt.decode(authorization[7:].strip(), settings.jwt_key, algorithms=[settings.jwt_algorithm],
                           audience=settings.jwt_audience,
                           options={"require": ["sub", "exp"], "verify_aud": settings.jwt_audience is not None})
        except jwt.PyJWTError:
            raise WorkflowError(401, "Invalid token")
        return c

    def officer(c: dict = Depends(claims)) -> str:
        return c["sub"]

    def coordinator(c: dict = Depends(claims)) -> str:
        roles = c.get("roles") or []
        if settings.coordinator_role not in (roles if isinstance(roles, list) else [roles]):
            raise WorkflowError(403, "Coordinator role required")
        return c["sub"]

    @app.exception_handler(WorkflowError)
    async def _wf(_: Request, e: WorkflowError):
        return _problem(e.status, e.title, e.detail)

    @app.exception_handler(UpstreamUnavailable)
    async def _up(_: Request, e: UpstreamUnavailable):
        return _problem(502, "UGPass unavailable")

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        return _problem(400, "Invalid request", "; ".join(f"{'.'.join(map(str, x['loc'][1:]))}: {x['msg']}" for x in e.errors()))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/api/v1/mous", status_code=201)
    def create(req: MouCreate, _: str = Depends(coordinator), s: Session = Depends(db)):
        return mou_view(service.create_mou(s, req), settings.public_base_url)

    @app.get("/api/v1/mous/{mou_id}")
    def get(mou_id: str, _: str = Depends(officer), s: Session = Depends(db)):
        return mou_view(service.get_mou(s, mou_id), settings.public_base_url)

    @app.post("/api/v1/mous/{mou_id}/signing-requests", status_code=202)
    def send_next(mou_id: str, _: str = Depends(coordinator), s: Session = Depends(db)):
        sig = service.send_next_request(s, client, mou_id)
        return {"requestId": sig.request_id, "signatoryName": sig.name, "sentAt": sig.sent_at.isoformat()}

    @app.post("/api/v1/mous/{mou_id}/e-seals")
    def seal(mou_id: str, _: str = Depends(coordinator), s: Session = Depends(db)):
        return mou_view(service.apply_seals(s, client, mou_id), settings.public_base_url)

    @app.get("/api/v1/mous/{mou_id}/verification")  # public: opened from the QR code
    def verification(mou_id: str, hash: str | None = None, s: Session = Depends(db)):
        return service.verify(service.get_mou(s, mou_id), hash)

    @app.post("/api/v1/callbacks/ugpass", status_code=204)
    async def callback(request: Request, x_ugpass_signature: str | None = Header(default=None),
                       s: Session = Depends(db)):
        raw = await request.body()
        if not verify_callback(settings.callback_secret, raw, x_ugpass_signature):
            raise WorkflowError(401, "Invalid callback signature")
        try:
            ev = UgpassEvent.model_validate_json(raw)
        except ValidationError:
            raise WorkflowError(400, "Invalid request", "malformed callback body")
        service.handle_callback(s, ev)
        return Response(status_code=204)

    return app
