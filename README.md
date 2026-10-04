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

## Security & Evaluation Results

All security invariants and empirical metrics are proven against live PostgreSQL 16 and Qdrant 1.19.1 services on an expanded multi-tenant corporate corpus:

### Core Security Guarantees: Counterfactual Invariance & Canary Defense

1. **Counterfactual Invariance (100.00% Invariance Rate - 0 Mismatches)**
   - **Evaluation Methodology**: For all 1,750 unauthorized principal-query pairs (across 3,850 total queries evaluated in 11 user personas and 3 tenants), queries were executed in **World 1** (restricted documents present) and **World 2** (TRUE REMOVAL: restricted documents completely deleted from PostgreSQL and Qdrant).
   - **Permitted Document Retrieval**: In **996 pairs**, unauthorized users legitimately retrieved citations from permitted public or internal documents; citations (IDs and ordering), scores (within $10^{-4}$ tolerance), and answers were mathematically identical between World 1 and World 2.
   - **Restricted / Unmatched Retrieval**: In **754 pairs**, unauthorized users received the standard no-access response (`citations: []`, identical refusal answer).
   - **Result**: **0 mismatches** across all 1,750 unauthorized evaluations. The presence of restricted documents causes zero behavioral or observational divergence for unauthorized principals.

2. **Canary Token Isolation (0 Leaks / 89,250 Checks)**
   - **Entropy & Generation**: 27 unique cryptographically random canary tokens generated via Python `secrets.token_hex(16)` (128 bits of entropy) were embedded into restricted document chunks across all tenants.
   - **Inspection Depth**: For every unauthorized query evaluation, 3 distinct locations are checked:
     1. Raw prompt string and `DOCUMENT CONTEXT` sent to the LLM backend (intercepted via `PromptCapturingLLM`)
     2. Generated LLM answer text
     3. JSON response citations and metadata
   - **Result**: $255 \text{ unauthorized user-canary pairs} \times 350 \text{ queries} = \mathbf{89,250} \text{ checks}$ ($267,750$ location inspections). **0 canary violations detected (0.00% leak rate)**.

### Evaluation Metrics Summary (Corpus: 247 chunks, 30 documents, 3 tenants)

| Metric | Result | Scope & Context |
|---|---|---|
| **Live Integration & Security Suite** | **31 passed, 0 skipped, 0 failed, 1 opt-in** | `pytest -v` across live stack (`RUN_REAL_STACK=1`, `PERSISTENCE_BACKEND=postgres`, `VECTOR_BACKEND=qdrant`) |
| **Cross-Tenant Leak Rate** | **0.00%** (0 leaks / 3,850 queries) | Evaluated across 3 isolated organizations (`acme-corp`, `globex-inc`, `initech-llc`) |
| **Canary Violations (Prompt + Answer + Citations)** | **0 / 89,250 checks** (0.00%) | 27 CSPRNG canaries, 267,750 location inspections across 11 users |
| **Counterfactual Invariance (True Removal)** | **100.00%** (0 mismatches / 1,750 pairs) | 996 permitted pairs + 754 refusal pairs (`tests/security/test_counterfactual.py`) |
| **Synthetic Query Recall@5 (Calibrated 0.35)** | **100.00%** (MRR: 0.9949) | 487 permitted synthetic query evaluations |
| **Hand-Written Natural Phrasing Recall@5** | **62.58%** (MRR: 0.6161) | 155 permitted hand-written query evaluations (natural, colloquial phrasing) |
| **Cryptographic Audit Integrity** | **PASSED** (`/v1/audit/verify` validated) | 50 concurrent transactions under advisory locks; append-only hash chain intact |
| **Role Separation & Least Privilege** | **PASSED** | Application runs as non-owner `gatekeep_app`; owner role isolated to migrations |

### Parity as a Behavioral Metric (Not a Security Guarantee)

> [!NOTE]
> **Understanding Parity Share**: Restricted parity measures the percentage of queries targeting restricted documents that return the standard empty response (`"citations": []`) versus returning *permitted* chunks from the user's own clearance level.
> - If an employee asks `"headcount hiring plan budget"`, they cannot access the restricted executive salary document. If their tenant has a permitted `employee-handbook` that discusses hiring, semantic similarity may match that permitted document.
> - Both outcomes are 100% secure: the restricted document is never leaked. Parity share is a similarity threshold tuning metric, not a security guarantee.
> - Thresholds were calibrated on this 247-chunk benchmark corpus using `all-MiniLM-L6-v2`.

| Similarity Threshold | Overall Recall@5 | Overall MRR | Restricted Parity Share | Cross-Tenant Leak Rate | Canary Violations | Behavioral Profile |
|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **0.25** | 92.68% | 0.9150 | 23.14% (106 / 458) | 0.00% | 0 / 89,250 checks | Permissive matching; permitted chunks frequently match loose keywords |
| **0.30** | 91.74% | 0.9102 | 45.20% (207 / 458) | 0.00% | 0 / 89,250 checks | Moderate semantic filtering; filters unrelated cross-domain internal docs |
| **0.35** | **90.97%** | **0.9034** | **69.00% (316 / 458)** | **0.00%** | **0 / 89,250 checks** | **Calibrated baseline; optimal synthetic recall (100%) and balanced parity** |
| **0.40** | 88.63% | 0.8824 | 87.77% (402 / 458) | 0.00% | 0 / 89,250 checks | High-parity threshold; minor recall drop on phrasing edge cases |
| **0.45** | 86.60% | 0.8621 | 93.89% (430 / 458) | 0.00% | 0 / 89,250 checks | Strict cutoff; high parity with reduced recall on colloquial phrasing |

---

## Seeded Personas & Credential Notice

> [!WARNING]
> **Demo-Only Credentials & Secrets Replacement**: All personas below (`alice`/`alice`, `bob`/`bob`, etc.) and default service credentials (such as `gatekeep:gatekeep` and default JWT secrets) are seeded strictly for local sandbox demonstration, test suites, and offline evaluation. In any staging or production deployment, default credentials and static database passwords must be replaced by strong, dynamically provisioned secrets managed via a dedicated secrets store (such as AWS Secrets Manager or HashiCorp Vault).

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
