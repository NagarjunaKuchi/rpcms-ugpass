import pytest
from fastapi.testclient import TestClient

from rpcms_ugpass.api import create_app, load_client, verify_callback
from rpcms_ugpass.config import Settings
from rpcms_ugpass.upstream import MockUgpassClient

from conftest import KEY, SECRET, auth, callback, mou_body


def create(c, **kw):
    r = c.post("/api/v1/mous", json=mou_body(**kw), headers=auth())
    assert r.status_code == 201, r.text
    return r.json()


def sign_all(c, mid, n=3):
    for _ in range(n):
        r = c.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth())
        assert r.status_code == 202, r.text
        assert callback(c, r.json()["requestId"]).status_code == 204


def test_full_happy_path(client):
    m = create(client)
    assert m["status"] == "DRAFT" and len(m["documentHashSha256"]) == 64
    assert m["verificationUrl"].endswith(f"/api/v1/mous/{m['mouId']}/verification")
    sign_all(client, m["mouId"])
    assert client.get(f"/api/v1/mous/{m['mouId']}", headers=auth()).json()["status"] == "SIGNED_AWAITING_SEALS"
    done = client.post(f"/api/v1/mous/{m['mouId']}/e-seals", headers=auth()).json()
    assert done["status"] == "COMPLETE"
    v = client.get(f"/api/v1/mous/{m['mouId']}/verification", params={"hash": m["documentHashSha256"]}).json()
    assert v["valid"] and v["documentUnchanged"] is True and v["verifiedSigners"] == 3 and v["verifiedSeals"] == 3
    bad = client.get(f"/api/v1/mous/{m['mouId']}/verification", params={"hash": "0" * 64}).json()
    assert bad["valid"] is False and bad["documentUnchanged"] is False
    assert client.get(f"/api/v1/mous/{m['mouId']}/verification").json()["documentUnchanged"] is None


def test_signing_is_sequential(client):
    mid = create(client)["mouId"]
    r1 = client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth())
    assert r1.json()["signatoryName"] == "Signer 1"
    assert client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth()).status_code == 409
    callback(client, r1.json()["requestId"])
    r2 = client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth())
    assert r2.json()["signatoryName"] == "Signer 2"


def test_seals_blocked_until_all_signed(client):
    mid = create(client)["mouId"]
    assert client.post(f"/api/v1/mous/{mid}/e-seals", headers=auth()).status_code == 409
    v = client.get(f"/api/v1/mous/{mid}/verification").json()
    assert v["valid"] is False and v["verifiedSigners"] == 0


def test_no_seal_required_completes_on_last_signature(client):
    mid = create(client, seal=False)["mouId"]
    sign_all(client, mid)
    assert client.get(f"/api/v1/mous/{mid}", headers=auth()).json()["status"] == "COMPLETE"


def test_decline_voids_and_expiry_allows_resend(client):
    mid = create(client)["mouId"]
    r = client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth()).json()
    assert callback(client, r["requestId"], "EXPIRED").status_code == 204
    again = client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth())
    assert again.status_code == 202 and again.json()["signatoryName"] == "Signer 1"
    assert callback(client, again.json()["requestId"], "DECLINED").status_code == 204
    assert client.get(f"/api/v1/mous/{mid}", headers=auth()).json()["status"] == "VOID"
    assert client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth()).status_code == 409


def test_callback_idempotent_and_conflict(client):
    mid = create(client)["mouId"]
    rid = client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth()).json()["requestId"]
    assert callback(client, rid).status_code == 204
    assert callback(client, rid).status_code == 204  # replay
    assert callback(client, rid, "DECLINED").status_code == 409
    assert callback(client, "UGP-REQ-UNKNOWN").status_code == 404


def test_callback_signature_enforced(client):
    mid = create(client)["mouId"]
    rid = client.post(f"/api/v1/mous/{mid}/signing-requests", headers=auth()).json()["requestId"]
    assert callback(client, rid, secret="wrong-secret-0123456789").status_code == 401
    assert client.post("/api/v1/callbacks/ugpass", json={"requestId": rid, "outcome": "APPROVED"}).status_code == 401
    assert client.get(f"/api/v1/mous/{mid}", headers=auth()).json()["signatories"][0]["status"] == "REQUEST_SENT"
    assert verify_callback(SECRET, b"x", None) is False


def test_validation_and_duplicates(client):
    create(client)
    assert client.post("/api/v1/mous", json=mou_body(), headers=auth()).status_code == 409
    dup_order = mou_body(ref="REF-2")
    dup_order["signatories"][1]["order"] = 1
    assert client.post("/api/v1/mous", json=dup_order, headers=auth()).status_code == 400
    assert client.post("/api/v1/mous", json={"programmeId": "x"}, headers=auth()).status_code == 400
    assert client.get("/api/v1/mous/NOPE", headers=auth()).status_code == 404


def test_officer_auth_required(client):
    assert client.post("/api/v1/mous", json=mou_body()).status_code == 401
    assert client.get("/api/v1/mous/X", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_seal_upstream_failure_returns_502_and_keeps_state():
    c = TestClient(create_app(Settings(jwt_key=KEY, callback_secret=SECRET, database_url="sqlite:///:memory:")))
    mid = create(c, orgs=("OPM", "DoR-NOSEAL"))["mouId"]
    sign_all(c, mid, 2)
    assert c.post(f"/api/v1/mous/{mid}/e-seals", headers=auth()).status_code == 502
    assert c.get(f"/api/v1/mous/{mid}", headers=auth()).json()["status"] == "SIGNED_AWAITING_SEALS"


def test_load_client_validation():
    assert isinstance(load_client("rpcms_ugpass.upstream.MockUgpassClient"), MockUgpassClient)
    with pytest.raises(ValueError):
        load_client("nodots")
    with pytest.raises(TypeError):
        load_client("collections.OrderedDict")


def test_hash_depends_on_terms_not_creation_time(client):
    a = create(client, ref="R-A")
    b = create(client, ref="R-B")
    assert a["documentHashSha256"] != b["documentHashSha256"]
