# rpcms-ugpass

MoU e-signing workflow adapter for RPCMS (OpenG2P Gen2 refugee partner coordination) around UGPass.
It runs the **sequence** (sequential personal signatures, then organisation e-Seals, then public verification);
UGPass itself is behind a pluggable `UgpassClient`.

Contract: [`openapi/rpcms-ugpass.yaml`](openapi/rpcms-ugpass.yaml)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/mous` | Create workflow; computes SHA-256 of the MoU terms (409 on duplicate reference) |
| `POST /api/v1/mous/{id}/signing-requests` | Send next request in `order`; 409 while a previous one is pending |
| `POST /api/v1/callbacks/ugpass` | Signatory approved/declined/expired (HMAC-signed, idempotent) |
| `POST /api/v1/mous/{id}/e-seals` | After all signatures: seal each organisation that needs one |
| `GET /api/v1/mous/{id}/verification` | Public (QR target); optional `?hash=` comparison |

States: `DRAFT -> SIGNING -> SIGNED_AWAITING_SEALS -> COMPLETE`; a decline makes it `VOID`; an expiry lets the same signatory be re-requested.

## Run
```
pip install -e ".[test]"
export RPCMS_UGPASS_JWT_KEY=...          # officer tokens (>=16 chars; 32+ for HS256)
export RPCMS_UGPASS_CALLBACK_SECRET=...  # >=16 chars
# optional: RPCMS_UGPASS_DATABASE_URL (default sqlite), _PUBLIC_BASE_URL, _CLIENT_IMPL
uvicorn --factory rpcms_ugpass.api:create_app
pytest
```

## Known limits (read before relying on this)
- **Nothing here talks to UGPass.** The UGPass interface, NGO/organisation onboarding and e-Seal availability are unconfirmed; only `MockUgpassClient` exists and it signs nothing.
- **The callback signature scheme (HMAC-SHA256 of the raw body, `X-UGPass-Signature`) is an assumption.** Replace `verify_callback` with whatever UGPass really uses.
- **`/verification` checks RPCMS's own records only.** It does not validate UGPass certificates or seals cryptographically, so it is not legal proof of a valid signature.
- The hash covers a canonical JSON of the MoU terms, not a rendered PDF. If signatures must cover a PDF, hash that file.
- Tables are created at startup with no migrations; use Alembic and PostgreSQL before production. Sequencing relies on one DB transaction per call and has not been load-tested for concurrency.
- Officer tokens carry no role or partner checks yet: any valid officer can drive any MoU.
- The 404/409 on the callback and the nullable `documentUnchanged` were added to the contract after the first draft.
