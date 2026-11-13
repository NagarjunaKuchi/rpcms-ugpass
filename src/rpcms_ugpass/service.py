"""MoU signing workflow. Pure domain logic over a SQLAlchemy session; HTTP lives in api.py.

States: DRAFT -> SIGNING -> SIGNED_AWAITING_SEALS -> COMPLETE (or VOID if a signatory declines).
Signatures are strictly sequential by ``order``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Mou, Seal, Signatory
from .schemas import MouCreate, UgpassEvent
from .upstream import UgpassClient


class WorkflowError(Exception):
    def __init__(self, status: int, title: str, detail: str = ""):
        super().__init__(title)
        self.status, self.title, self.detail = status, title, detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def document_hash(req: MouCreate) -> str:
    """SHA-256 over canonical JSON of the MoU's terms. This hashes RPCMS's structured record of
    the MoU, NOT a rendered PDF; if signing must cover a PDF, hash that file instead."""
    canon = {
        "reference": req.reference, "programmeId": req.programmeId, "ampRecordId": req.ampRecordId,
        "signatories": sorted(
            ({"name": s.name, "role": s.role, "organisation": s.organisation, "order": s.order,
              "sealRequired": s.sealRequired} for s in req.signatories), key=lambda x: x["order"]),
    }
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_mou(session: Session, req: MouCreate) -> Mou:
    orders = [s.order for s in req.signatories]
    if len(set(orders)) != len(orders):
        raise WorkflowError(400, "Invalid request", "signatory order values must be unique")
    mou = Mou(id="MOU-" + secrets.token_hex(6).upper(), reference=req.reference,
              programme_id=req.programmeId, amp_record_id=req.ampRecordId,
              document_hash=document_hash(req), status="DRAFT")
    mou.signatories = [Signatory(name=s.name, role=s.role, organisation=s.organisation, order=s.order,
                                 seal_required=s.sealRequired) for s in req.signatories]
    session.add(mou)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise WorkflowError(409, "Duplicate MoU", f"a MoU with reference {req.reference!r} already exists")
    return mou


def get_mou(session: Session, mou_id: str) -> Mou:
    mou = session.get(Mou, mou_id)
    if mou is None:
        raise WorkflowError(404, "MoU not found")
    return mou


def send_next_request(session: Session, client: UgpassClient, mou_id: str) -> Signatory:
    mou = get_mou(session, mou_id)
    if mou.status not in ("DRAFT", "SIGNING"):
        raise WorkflowError(409, "MoU not accepting signing requests", f"status is {mou.status}")
    if any(s.status == "REQUEST_SENT" for s in mou.signatories):
        raise WorkflowError(409, "Previous signatory has not yet signed")
    nxt = next((s for s in mou.signatories if s.status in ("WAITING", "EXPIRED")), None)
    if nxt is None:
        raise WorkflowError(409, "No signatory left to request")
    # Reserve the slot first so two concurrent callers cannot both send to the same signatory.
    nxt.status = "REQUEST_SENT"
    mou.status = "SIGNING"
    session.flush()
    try:
        nxt.request_id = client.send_signing_request(mou.id, mou.document_hash, nxt.name)
    except Exception:
        session.rollback()
        raise
    nxt.sent_at = _now()
    session.commit()
    return nxt


def handle_callback(session: Session, ev: UgpassEvent) -> None:
    sig = session.scalar(select(Signatory).where(Signatory.request_id == ev.requestId))
    if sig is None:
        raise WorkflowError(404, "Unknown request id")
    target = {"APPROVED": "SIGNED", "DECLINED": "DECLINED", "EXPIRED": "EXPIRED"}[ev.outcome]
    if sig.status == target:
        return  # idempotent replay
    if sig.status != "REQUEST_SENT":
        raise WorkflowError(409, "Conflicting callback", f"signatory already {sig.status}")
    mou = sig.mou
    sig.status = target
    if target == "SIGNED":
        sig.certificate_ref = ev.certificateRef
        sig.signed_at = ev.signedAt or _now()
        if all(s.status == "SIGNED" for s in mou.signatories):
            mou.status = "SIGNED_AWAITING_SEALS" if any(s.seal_required for s in mou.signatories) else "COMPLETE"
    elif target == "DECLINED":
        mou.status = "VOID"
    session.commit()


def apply_seals(session: Session, client: UgpassClient, mou_id: str) -> Mou:
    mou = get_mou(session, mou_id)
    if mou.status != "SIGNED_AWAITING_SEALS":
        raise WorkflowError(409, "MoU not ready for seals", f"status is {mou.status}")
    sealed = {s.organisation for s in mou.seals}
    for org in sorted({s.organisation for s in mou.signatories if s.seal_required} - sealed):
        ref = client.apply_seal(mou.id, mou.document_hash, org)  # may raise; earlier seals are kept
        mou.seals.append(Seal(organisation=org, seal_ref=ref))
        session.commit()
    mou.status = "COMPLETE"
    session.commit()
    return mou


def verify(mou: Mou, supplied_hash: str | None) -> dict:
    """Checks RPCMS's own record only. It does NOT validate UGPass certificates cryptographically."""
    signed = sum(1 for s in mou.signatories if s.status == "SIGNED")
    needed = {s.organisation for s in mou.signatories if s.seal_required}
    sealed = {s.organisation for s in mou.seals}
    unchanged = None if supplied_hash is None else supplied_hash.lower() == mou.document_hash
    complete = mou.status == "COMPLETE" and signed == len(mou.signatories) and needed <= sealed
    return {"valid": bool(complete and unchanged is not False), "documentUnchanged": unchanged,
            "verifiedSigners": signed, "verifiedSeals": len(sealed & needed), "checkedAt": _now()}
