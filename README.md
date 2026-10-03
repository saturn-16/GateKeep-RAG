# GateKeep RAG: Permission-Aware Multi-Tenant RAG Service

GateKeep RAG is an enterprise-grade, permission-aware multi-tenant Retrieval-Augmented Generation (RAG) platform built with FastAPI, PostgreSQL + Alembic, Qdrant vector database, local sentence-transformer embeddings, and local/remote LLM support (MockLLM / Ollama `llama3.2:3b`).

Every document chunk carries tenant ownership and role/clearance access control lists (ACLs). Search is pre-filtered directly inside Qdrant before vector similarity search, post-verified against PostgreSQL before prompt compilation, and cryptographically recorded in an append-only, hash-chained audit ledger.

---

## Architecture Diagram

```mermaid
flowchart TD
    Client["Client / Frontend"] -->|1. JWT Bearer Token + Query| API["FastAPI Gateway"]
    API -->|2. Verify Signature & Resolve Identity| Auth["Auth Dependency\n(scrypt / HMAC-SHA256)"]
    Auth -->|3. Principal Context\n(tenant_id, roles, clearance)| Retriever["TenantScopedRetriever"]
    
    subgraph VectorSearch ["Stage 1: Pre-Filtered Vector Search"]
        Retriever -->|4. build_filter(principal)\nAdditive status=ready| Qdrant["Qdrant Vector DB\n(Cosine Similarity, 384d)"]
        Qdrant -->|5. Candidate Chunks| Retriever
    end

    subgraph DefenseInDepth ["Stage 2: Defense-in-Depth Verification"]
        Retriever -->|6. can_access(principal, acl)\nDocument status == ready| Postgres["PostgreSQL 16\n(chunks, documents, roles)"]
        Postgres -.->|Mismatch Alert| SecurityAlert["Audit: security_alert"]
        Postgres -->|7. Verified Chunks Only| PromptBuilder["Grounded Prompt Builder"]
    end

    subgraph Generation ["Stage 3: Grounded Synthesis & Guardrails"]
        PromptBuilder -->|8. Grounded Context| LLM["LLM Provider\n(MockLLM / Ollama llama3.2:3b)"]
        LLM -->|9. Raw Output| OutputGuard["OutputGuard\n(Citation Scrubber)"]
        OutputGuard -->|10. Guarded Answer| AuditService["Audit Service\n(pg_advisory_xact_lock)"]
    end

    subgraph AuditLog ["Stage 4: Tamper-Evident Hash Chain"]
        AuditService -->|11. SHA-256 Hash-Chained Row| AuditTable["PostgreSQL audit_logs\n(Non-owner gatekeep_app role)"]
        AuditTable -->|12. Final Response with Citations & audit_id| Client
    end
```

---

## Demo Preview

<!-- demo gif placeholder -->
```
+-----------------------------------------------------------------------------------------+
|                                GATEKEEP / ACCESS-AWARE RAG                              |
|                          One question. Different truth.                                 |
+------------------------------------+----------------------------------------------------+
|  Persona: Bob (Acme HR)            |  Persona: Dave (Acme Employee)                     |
|  Query: "Engineer salary bands?"   |  Query: "Engineer salary bands?"                   |
|                                    |                                                    |
|  Answer:                           |  Answer:                                           |
|  The salary band for engineers is  |  "I don't have access to information               |
|  145,000 base pay with stock.      |  that answers this."                               |
|                                    |                                                    |
|  Citations: [salary-bands-2026]    |  Citations: [] (Standard no-results response)      |
+------------------------------------+----------------------------------------------------+
```
*(Demo GIF placeholder: see `docs/DEMO.md` for live CLI and React demo walkthrough)*

---

## Test & Evaluation Results

All metrics are proven against the live PostgreSQL 16 and Qdrant 1.19.1 services:

| Check / Metric | Result | Verification Evidence |
|---|---|---|
| **Live Integration & Security Suite** | **31 passed, 0 skipped, 0 failed** (100% pass) | `pytest -v` across real stack (`RUN_REAL_STACK=1`, `PERSISTENCE_BACKEND=postgres`) |
| **Tenants Evaluated** | **3 distinct tenants** (`acme-corp`, `globex-inc`, `initech-llc`) | `scripts/run_eval.py` |
| **Personas & Clearances Evaluated** | **11 users** across admin, HR, finance, engineering, employee | `scripts/run_eval.py` |
| **User-Query Pairs Checked** | **1,045 pairs** (including prompt injection & adversarial probes) | `scripts/run_eval.py` |
| **Cross-Tenant Leak Rate** | **0.00%** (0 leaks / 1,045 queries) | `scripts/run_eval.py` |
| **Canary Token Violations** | **0 / 5,415 checks** (0 violations across all unauthorized pairs) | `scripts/run_eval.py` (6 unique canary tokens in restricted docs) |
| **Recall@5 (Permitted Queries)** | **92.86%** (78 / 84 permitted queries) | `scripts/run_eval.py` |
| **MRR (Mean Reciprocal Rank)** | **0.8750** | `scripts/run_eval.py` |
| **Default Embedding Model** | `all-MiniLM-L6-v2` (384 dimensions, sentence-transformers) | `app/rag/embeddings/sentence_transformer.py` |
| **Cryptographic Audit Integrity** | **PASSED** (`/v1/audit/verify` validated) | `tests/integration/test_audit_concurrency.py`, `tests/integration/test_audit_completeness.py` |
| **Dependency & Secret Scans** | **0 vulnerabilities, 0 secret leaks** | `pip-audit`, `gitleaks` (32 commits scanned) |

### Threshold Sensitivity Analysis (Eval Corpus: 18 chunks, 1,045 query pairs)

> [!NOTE]
> The similarity score threshold was tuned on the demo corpus using `all-MiniLM-L6-v2`. At `threshold = 0.35`, exact no-results response parity reaches 100.00% (81/81) while preserving 92.86% Recall@5 and 0.8750 MRR for permitted queries.

| Threshold | Recall@5 | MRR | Restricted Parity Share | Leak Rate | Canary Violations | Behavioral Profile |
|---|---|---|---|---|---|---|
| **0.25** | 92.86% | 0.8750 | 83.95% (68 / 81) | 0.00% | 0 / 5,415 checks | Broad semantic matching; loose cross-document overlap |
| **0.30** | 92.86% | 0.8750 | 98.77% (80 / 81) | 0.00% | 0 / 5,415 checks | Default; 1 query matched permitted handbook chunk |
| **0.35** | 92.86% | 0.8750 | 100.00% (81 / 81) | 0.00% | 0 / 5,415 checks | Calibrated; zero cross-document false positives |

---

## Seeded Personas (Demo-Only Credentials)

> [!WARNING]
> **Demo-Only Credentials**: The credentials below (`alice`/`alice`, `bob`/`bob`, etc.) are seeded strictly for local sandbox demonstration, test suites, and evaluation. Never deploy default or username-identical passwords in a staging or production environment.

| Username | Password | Tenant | Roles | Clearance | Description |
|---|---|---|---|---|---|
| `alice` | `alice` | `acme-corp` | `admin` | `restricted` | Acme Tenant Administrator |
| `bob` | `bob` | `acme-corp` | `hr` | `restricted` | Acme HR Specialist (can see salaries) |
| `carol` | `carol` | `acme-corp` | `finance` | `confidential` | Acme Finance Analyst |
| `dave` | `dave` | `acme-corp` | `employee` | `internal` | Acme General Employee (no salary access) |
| `frank` | `frank` | `globex-inc` | `admin` | `restricted` | Globex Tenant Administrator |

---

## Quickstart

### 1. Requirements & Prerequisites
- Python 3.11+
- Docker and Docker Compose
- Node.js 18+ (for frontend)
- (Optional) Ollama with `llama3.2:3b` for local generative synthesis

### 2. Launch Stack
```bash
# 1. Clone repository
git clone https://github.com/saturn-16/GateKeep-RAG.git
cd GateKeep-RAG

# 2. Configure environment
cp .env.example .env
# Edit .env and supply a secure JWT_SECRET

# 3. Start PostgreSQL 16 and Qdrant 1.19.1
docker compose up -d --build

# 4. Install python dependencies
python -m pip install -e ".[test,security]"

# 5. Run database migrations
alembic upgrade head

# 6. Seed demo dataset (3 tenants, 11 users, vector embeddings)
python scripts/seed_demo.py
```

### 3. Run Live Test Suite & Security Matrix
```bash
$env:RUN_REAL_STACK="1"
$env:PERSISTENCE_BACKEND="postgres"
$env:VECTOR_BACKEND="qdrant"
python -m pytest -v
```

### 4. Run Expanded Evaluation Suite (1,000+ Queries)
```bash
python scripts/run_eval.py
```

### 5. Launch React Demo UI
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` to explore Ask, Role Comparison, and Audit Explorer.

---

## Security Model & Invariants

1. **Pre-Filter Invariant**: Every Qdrant vector retrieval requires `tenant_id` and role conditions (`build_filter(principal)`). Status condition (`status = ready`) is strictly additive.
2. **Post-Retrieval Verification**: Retrieved chunks are checked against PostgreSQL permissions (`can_access`) prior to prompt synthesis; unpermitted chunks raise a `security_alert`.
3. **No-Results Parity**: Queries against restricted content yield identical schema, HTTP status, and body shape as queries with zero search matches.
4. **Append-Only Hash Chain**: Audit records are signed with SHA-256 chaining per tenant, protected with PostgreSQL advisory transaction locks and dedicated non-owner role privileges (`gatekeep_app`).
5. **Immediate Role Revocation**: Revocations apply immediately on the subsequent request.

For the comprehensive threat model matrix and vulnerability mitigations, see [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Limitations & Implementation Status

| Capability | Status | Notes |
|---|---|---|
| **Multi-Tenant Vector Pre-filtering** | **Done** | Enforced via Qdrant native filters and TenantScopedRetriever |
| **Post-Retrieval ACL Verification** | **Done** | Verified against PostgreSQL before prompt assembly |
| **Cryptographic Audit Hash Chain** | **Done** | Verified via `/v1/audit/verify` with transaction advisory locks |
| **Document Ingestion (PDF, DOCX, MD, TXT)** | **Done** | Multipart parser with background status transitions (`ready`/`failed`) |
| **Local Embedding Pipeline** | **Done** | `all-MiniLM-L6-v2` sentence-transformers with cosine threshold |
| **Ollama Local LLM Support** | **Done** | Tested end-to-end with `llama3.2:3b`; `MockLLM` default for fast tests |
| **Distributed Rate Limiting** | **Partial** | Sliding-window DB rate limiter implemented; Redis token bucket planned |
| **Streaming Chunked Output** | **Omitted** | Omitted intentionally to preserve post-generation citation output guards |
| **Full Admin CRUD & Enterprise SSO** | **Pending** | User creation and role assignment implemented; OIDC/SAML/SCIM on roadmap |

---

## Resume Bullet Variants

### Variant 1: Security & Distributed Systems Focus
> Architected a permission-aware multi-tenant RAG platform using FastAPI, PostgreSQL, and Qdrant, enforcing defense-in-depth with vector pre-filtering, relational ACL re-verification, and an append-only SHA-256 audit hash chain, achieving 0.00% cross-tenant data leakage across a 1,045-query evaluation benchmark.

### Variant 2: Full-Stack AI & Infrastructure Focus
> Engineered an enterprise RAG service featuring dual vector/relational access control, local embedding models (`all-MiniLM-L6-v2`), and local LLM integration (`llama3.2:3b`), paired with an interactive React audit and side-by-side role comparison frontend and CI/CD pipelines incorporating pip-audit and gitleaks scanning.

### Variant 3: Machine Learning & Eval Focus
> Designed and executed an expanded 1,045-query adversarial evaluation suite measuring multi-tenant RAG security, validating 0.00% leak rate against prompt injections, 92.86% Recall@5, 0.8750 MRR for permitted queries, and 98.77% response shape parity for restricted queries.
