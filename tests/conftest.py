import os
import hashlib
import hmac
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from rpcms_ugpass.api import create_app
from rpcms_ugpass.config import Settings

KEY = "test-signing-key-0123456789-abcdef"
SECRET = "callback-secret-0123456789"


@pytest.fixture
def client():
    s = Settings(jwt_key=KEY, callback_secret=SECRET, database_url=os.environ.get("RPCMS_TEST_DATABASE_URL", "sqlite:///:memory:"), create_tables="RPCMS_TEST_DATABASE_URL" not in os.environ)
    return TestClient(create_app(s))


def auth(roles=None):
    claims = {"sub": "off-1", "exp": int(time.time()) + 300}
    if roles:
        claims["roles"] = roles
    t = jwt.encode(claims, KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


def admin():
    return auth(["mou-admin"])


def mou_body(ref="OPM/DoR/NHU/2026/014", seal=True, orgs=("OPM", "DoR", "NHU")):
    return {"programmeId": "PRG-1", "reference": ref, "ampRecordId": "AMP-UG-2026-00731",
            "signatories": [{"name": f"Signer {i}", "role": "Director", "organisation": o, "order": i,
                             "sealRequired": seal} for i, o in enumerate(orgs, 1)]}


def callback(client, request_id, outcome="APPROVED", secret=SECRET, extra=None):
    body = json.dumps({"requestId": request_id, "outcome": outcome, "certificateRef": "CERT-1", **(extra or {})}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/v1/callbacks/ugpass", content=body,
                       headers={"X-UGPass-Signature": sig, "Content-Type": "application/json"})


@pytest.fixture(autouse=True)
def _clean_external_db():
    """With RPCMS_TEST_DATABASE_URL set (a throwaway Postgres already migrated with `alembic upgrade head`),
    empty the tables between tests. In-memory SQLite (default) needs nothing."""
    url = os.environ.get("RPCMS_TEST_DATABASE_URL")
    if url:
        from sqlalchemy import create_engine, text
        with create_engine(url).begin() as c:
            c.execute(text("TRUNCATE mou, seal, signatory RESTART IDENTITY CASCADE"))
    yield
