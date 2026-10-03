# Master Prompt Requirements Matrix

| Requirement | Implementation | Test / evidence | Status |
|---|---|---|---|
| Tenant-scoped Qdrant pre-filter | `src/app/rag/vectorstore/qdrant_store.py`, `src/app/core/permissions.py` | `tests/integration/test_real_stack.py`, `tests/security/test_tenant_scoping.py` | Done |
| DB tenants/users/roles/documents/chunks | `src/app/db/models.py`, `alembic/versions/0001_initial.py` | live migration and seed | Done |
| JWT login/refresh/me with current DB roles | `src/app/api/auth.py`, `src/app/api/dependencies.py`, `src/app/db/repository.py` | `tests/integration/test_live_security.py` | Done |
| Multipart PDF/DOCX/MD/TXT ingestion | `src/app/rag/ingestion/loaders.py`, `src/app/api/documents.py` | parser/unit coverage; live upload coverage pending | Partial |
| Background document status | `src/app/api/documents.py` | status route exists; DB document status persistence pending | Partial |
| ACL update/delete with repair state | `src/app/api/documents.py`, `src/app/rag/vectorstore/qdrant_store.py` | `tests/integration/test_document_mutations.py` | Done |
| Query pre-filter, DB post-verification, guarded citations | `src/app/api/query.py`, `src/app/rag/generation/` | `tests/integration/test_live_security.py`, `tests/security/test_query_existence.py` | Done |
| MockLLM and Ollama | `src/app/rag/llm.py` | MockLLM live; Ollama installed but no local models | Partial |
| Append-only hash-chain audit | `src/app/audit/`, `src/app/db/repository.py`, migration trigger | `tests/integration/test_live_security.py`, `tests/integration/test_audit_concurrency.py` | Done |
| Audit logs/export/verify/who-saw | `src/app/api/audit.py` | live audit scope/tamper checks | Done |
| Per-tenant concurrent audit writes | `src/app/db/repository.py` advisory lock | 50-query live concurrency test | Done |
| Mutation-proof tenant isolation test | `tests/security/test_filter_mutation.py` | mutation must fail isolation assertion | Done |
| Rate limiting | `src/app/core/rate_limit.py`, `src/app/api/auth.py`, `src/app/api/dependencies.py` | `tests/integration/test_rate_limit.py` | Done |
| Tenant admin user/role management | `src/app/api/admin.py` | `tests/integration/test_admin_endpoints.py` | Done |
| Seed dataset | `scripts/seed_demo.py` | live run: 2 tenants, 8 users, 10 chunks | Done |
| Attack demo and eval | `scripts/attack_demo.py`, `eval/run.py` | live PASS; leak rate 0.000 | Done |
| Windows task runner | `tasks.ps1` | `tasks.ps1 lint` | Done |
| CI services/security scans | `.github/workflows/ci.yml` | GitHub Actions run after remediation pending | Pending |
| Admin CRUD, ACL update/delete, streaming, full audit middleware | `src/app/api/` | not implemented | Pending |
