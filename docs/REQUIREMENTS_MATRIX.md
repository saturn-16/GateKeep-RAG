# Master Prompt Requirements Matrix

| Requirement | Implementation | Test / Evidence | Status |
|---|---|---|---|
| Tenant-scoped Qdrant pre-filter | `src/app/rag/vectorstore/qdrant_store.py`, `src/app/core/permissions.py` | `tests/integration/test_real_stack.py`, `tests/security/test_tenant_scoping.py` | Done |
| DB tenants/users/roles/documents/chunks | `src/app/db/models.py`, `alembic/versions/` (0001, 0002, 0003) | Live PostgreSQL migrations and seed | Done |
| JWT login/refresh/me with current DB roles | `src/app/api/auth.py`, `src/app/api/dependencies.py`, `src/app/db/repository.py` | `tests/integration/test_live_security.py` | Done |
| Multipart PDF/DOCX/MD/TXT ingestion | `src/app/rag/ingestion/loaders.py`, `src/app/api/documents.py` | `tests/integration/test_multipart_ingestion.py` (live HR upload vs employee denial) | Done |
| Background document status | `src/app/api/documents.py`, `src/app/db/models.py` | `tests/integration/test_document_status.py` (processing & failed are non-retrievable) | Done |
| ACL update/delete with repair state | `src/app/api/documents.py`, `src/app/rag/vectorstore/qdrant_store.py` | `tests/integration/test_document_mutations.py` | Done |
| Query pre-filter, DB post-verification, guarded citations | `src/app/api/query.py`, `src/app/rag/generation/` | `tests/integration/test_live_security.py`, `tests/security/test_query_existence.py` | Done |
| MockLLM and Ollama | `src/app/rag/llm.py`, `src/app/config.py` | `tests/integration/test_ollama_smoke.py`, `docs/DEMO.md` (`llama3.2:3b` verified) | Done |
| Append-only hash-chain audit | `src/app/audit/`, `src/app/db/repository.py`, migration trigger | `tests/integration/test_live_security.py`, `tests/integration/test_audit_concurrency.py` | Done |
| Audit completeness & verify endpoint | `src/app/api/audit.py`, `src/app/api/auth.py` | `tests/integration/test_audit_completeness.py` (all actions audited with exactly 1 row) | Done |
| Per-tenant concurrent audit writes | `src/app/db/repository.py` advisory lock | `tests/integration/test_audit_concurrency.py` (50 concurrent queries) | Done |
| Database role separation for audit | `alembic/versions/0003_app_role_audit_permissions.py` | `tests/integration/test_audit_role_safety.py` (non-owner role cannot drop trigger) | Done |
| Document ID & Tenant Safety | `src/app/api/documents.py`, `src/app/api/query.py` | `tests/integration/test_tenant_id_safety.py` (server UUID generation, cross-tenant 404) | Done |
| Mutation-proof tenant isolation test | `tests/security/test_filter_mutation.py` | Mutation of tenant filter fails isolation assertion | Done |
| Rate limiting & lockout | `src/app/core/rate_limit.py`, `src/app/api/auth.py` | `tests/integration/test_rate_limit.py` | Done |
| Tenant admin user/role management | `src/app/api/admin.py` | `tests/integration/test_admin_endpoints.py` | Done |
| Seed dataset | `scripts/seed_demo.py` | 3 tenants, 11 users, vector embeddings | Done |
| Attack demo and expanded eval | `scripts/run_eval.py` | 1,045 pairs across 3 tenants: 0.00% leak rate, 92.86% Recall@5, 0.8750 MRR | Done |
| Demo frontend UI | `frontend/` (React + Vite) | Ask with citations, side-by-side role compare, audit chain verification & who-saw | Done |
| Windows task runner | `tasks.ps1` | `tasks.ps1 lint`, `tasks.ps1 test` | Done |
| CI services/security scans | `.github/workflows/ci.yml` | Live PostgreSQL/Qdrant stack, pip-audit, gitleaks | Done |
| Admin full CRUD & Enterprise SSO | `src/app/api/admin.py` | Essential user/role endpoints implemented; full CRUD & SSO on roadmap | Pending |
| Streaming responses | `src/app/api/query.py` | Intentionally omitted to guarantee complete citation guardrails and audit | Omitted |
