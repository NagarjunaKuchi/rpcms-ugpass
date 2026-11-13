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
    s = Settings(jwt_key=KEY, callback_secret=SECRET, database_url="sqlite:///:memory:")
    return TestClient(create_app(s))


def auth():
    t = jwt.encode({"sub": "off-1", "exp": int(time.time()) + 300}, KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


def mou_body(ref="OPM/DoR/NHU/2026/014", seal=True, orgs=("OPM", "DoR", "NHU")):
    return {"programmeId": "PRG-1", "reference": ref, "ampRecordId": "AMP-UG-2026-00731",
            "signatories": [{"name": f"Signer {i}", "role": "Director", "organisation": o, "order": i,
                             "sealRequired": seal} for i, o in enumerate(orgs, 1)]}


def callback(client, request_id, outcome="APPROVED", secret=SECRET, extra=None):
    body = json.dumps({"requestId": request_id, "outcome": outcome, "certificateRef": "CERT-1", **(extra or {})}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/v1/callbacks/ugpass", content=body,
                       headers={"X-UGPass-Signature": sig, "Content-Type": "application/json"})
