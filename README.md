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

## Database migrations
Schema changes are managed with Alembic (`migrations/`, initial revision `0001`). For anything beyond local development:
```
pip install -e ".[postgres]"
export RPCMS_UGPASS_DATABASE_URL=postgresql+psycopg://user:pass@host/db  RPCMS_UGPASS_CREATE_TABLES=false
alembic upgrade head
```
`RPCMS_UGPASS_CREATE_TABLES` defaults to `true` (tables auto-created at startup, for development and tests); set it to `false` where Alembic owns the schema. A test checks that the migrations produce exactly the model schema. To run the suite against a migrated Postgres: `RPCMS_TEST_DATABASE_URL=... pytest` (it truncates the tables between tests, so use a throwaway database).

## Known limits (read before relying on this)
- **Nothing here talks to UGPass.** The UGPass interface, NGO/organisation onboarding and e-Seal availability are unconfirmed; only `MockUgpassClient` exists and it signs nothing.
- **The callback signature scheme (HMAC-SHA256 of the raw body, `X-UGPass-Signature`) is an assumption.** Replace `verify_callback` with whatever UGPass really uses.
- **`/verification` checks RPCMS's own records only.** It does not validate UGPass certificates or seals cryptographically, so it is not legal proof of a valid signature.
- The hash covers a canonical JSON of the MoU terms, not a rendered PDF. If signatures must cover a PDF, hash that file.
- Migrations exist for the current schema only (one initial revision), verified on PostgreSQL 16 locally (upgrade, downgrade, full test suite) but not on other versions. Sequencing relies on one DB transaction per call and has not been load-tested for concurrency.
- **Access:** creating an MoU, sending signing requests and applying e-seals need the role in `RPCMS_UGPASS_COORDINATOR_ROLE` (default `mou-admin`) in the JWT `roles` claim (403 otherwise); any valid officer can read an MoU, and the verification endpoint is public. MoUs have no owner partner: any coordinator can drive any MoU. The `roles` claim name and format are an assumption about the token issuer.
- The 404/409 on the callback and the nullable `documentUnchanged` were added to the contract after the first draft.
