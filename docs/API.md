# API

- `POST /v1/auth/login` accepts `{username,password}` and returns a bearer token.
- `GET /v1/me` returns the verified identity.
- `POST /v1/query` accepts `{question,top_k}` and returns answer, citations, and audit ID.
- `POST /v1/documents/text` ingests ACL'd text for permitted roles.
- `GET /v1/audit/logs` and `GET /v1/audit/verify` are tenant-admin-only.
- `GET /healthz` and `GET /readyz` expose liveness/readiness.

Tenant and roles are never accepted as authorization inputs; they come from the active user record and signed token.
