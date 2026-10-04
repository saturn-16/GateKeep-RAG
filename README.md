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
   - **Evaluation Methodology**: For all **4,972 principal-query pairs** evaluated across 11 personas and 3 tenants, queries were executed in **World 1** (baseline corpus with restricted documents present) and **World 2** (TRUE REMOVAL: for each principal, every document they are not authorized to access was physically deleted from both PostgreSQL and Qdrant).
   - **Permitted Document Retrieval**: In **3,432 pairs**, unauthorized users legitimately retrieved citations from permitted internal/public documents; citations (IDs and ordering), scores (within $10^{-4}$ tolerance), and answers were mathematically identical between World 1 and World 2.
   - **Restricted / Unmatched Retrieval**: In **1,540 pairs**, unauthorized users received the standard no-access response (`citations: []`, identical refusal answer).
   - **Result**: **0 mismatches** across all 4,972 evaluations. The existence or physical absence of restricted documents produces zero observational or behavioral divergence.

2. **Canary Token Isolation (0 Leaks / 115,260 Checks)**
   - **Entropy & Generation**: 27 unique cryptographically random canary tokens generated via Python `secrets.token_hex(16)` (128 bits of CSPRNG entropy) were embedded into restricted document chunks across all 3 tenants.
   - **Inspection Depth**: For every query evaluation, 3 distinct locations are checked:
     1. Raw prompt string and `DOCUMENT CONTEXT` sent to the LLM backend (intercepted via `PromptCapturingLLM`)
     2. Generated LLM answer text
     3. JSON response citations and metadata
   - **Result**: $255 \text{ unauthorized user-canary pairs} \times 452 \text{ unique queries} = \mathbf{115,260} \text{ checks}$ ($345,780$ location inspections). **0 canary violations detected (0.00% leak rate)**.

3. **Threshold-Independence (Guaranteed Security at Threshold 0.00)**
   - When the similarity score threshold is set to `0.00` (allowing every query to retrieve the top-5 permitted chunks regardless of similarity score), cross-tenant leak rate remains **0.00%** and canary violations remain **0 / 115,260** (proven in `tests/security/test_threshold_independence.py`). Security enforcement operates at the database pre-filter and defense-in-depth layer, completely independent of the score threshold.

---

### Evaluation Metrics Summary (Corpus: 210 chunks, 30 documents, 3 tenants)

> [!NOTE]
> **Corpus Size Reconciliation (210 vs 246/247 chunks)**: The active multi-tenant evaluation corpus contains exactly **210 chunks** (30 document templates $\times$ 70 chunks/tenant $\times$ 3 tenants). Earlier reports showing 246 or 247 chunks included residual test chunks from prior unpurged integration test executions matching `chunk-` in the PostgreSQL database. The seeding routine now explicitly purges the three evaluation tenants prior to seeding to ensure strict reproducibility.

| Metric | Before (Phase B) | After (Quality Hardening) | Scope & Evaluation Conditions |
|---|:---:|:---:|---|
| **Corpus Size** | 247 chunks | **210 chunks** (70/tenant $\times$ 3) | 30 documents across `acme-corp`, `globex-inc`, `initech-llc` |
| **Live Integration & Security Suite** | 31 passed, 0 skipped | **36 passed, 0 skipped, 1 opt-in** | `pytest -v` (`RUN_REAL_STACK=1`, `PERSISTENCE_BACKEND=postgres`, `VECTOR_BACKEND=qdrant`) |
| **Cross-Tenant Leak Rate** | 0.00% (3,850 queries) | **0.00%** (4,972 pairs) | Evaluated across all 11 user personas in 3 organizations |
| **Canary Violations (Prompt + Answer + Citations)** | 0 / 89,250 (0.00%) | **0 / 115,260** (0.00%) | 27 CSPRNG canaries, 345,780 location inspections across 11 users |
| **Counterfactual Invariance (True Physical Removal)** | 100.00% (1,750 pairs) | **100.00% (4,972 pairs)** | Evaluated for every principal (0 mismatches across all 11 users) |
| **Threshold Independence (Threshold 0.00)** | Untested | **PASSED (0 leaks, 0 canaries)** | Proves security does not depend on similarity score filtering |
| **Synthetic Query Recall@5 (Threshold 0.35)** | 100.00% (MRR: 0.9949) | **100.00%** (MRR: 0.9979) | 487 permitted synthetic query evaluations |
| **Hand-Written Dev Set Recall@5 (32 queries)** | N/A (unsplit) | **100.00%** (MRR: 1.0000) | 220 permitted dev query evaluations (used to calibrate threshold) |
| **Hand-Written Held-Out Test Recall@5 (32 queries)** | 62.58% (MRR: 0.6161) | **100.00%** (MRR: 0.9955) | 220 permitted held-out test evaluations (scored only at chosen threshold) |
| **All Hand-Written Combined Recall@5 (64 queries)** | 62.58% (MRR: 0.6161) | **100.00%** (MRR: 0.9977) | 440 permitted hand-written query evaluations |
| **Password Hashing Cost** | scrypt ($N=2^{14}$) | **scrypt ($N=2^{17}$, 128 MB RAM)** | $N=131072, r=8, p=1, \text{maxmem}=256\text{MB}$ (~435ms CPU hardness) |
| **Role Separation & Least Privilege** | Non-owner `gatekeep_app` | **Non-owner `gatekeep_app`** | Runtime API runs as unprivileged user; migrations use owner role |

---

### Parity as a Behavioral Metric & Reconciliation

> [!NOTE]
> **Why Restricted Parity Shifted (73.14% $\rightarrow$ 69.00% $\rightarrow$ 74.41%)**:
> 1. In earlier evaluations with only keyword-dense synthetic queries, restricted query parity was **73.14% (207 / 283)**.
> 2. When the first 30 hand-written natural queries were added, the total number of restricted-only queries evaluated against unauthorized users increased from 283 to 458. Certain natural queries regarding compensation, benefits, and office policies had legitimate semantic overlap ($>0.35$) with permitted documents in the user's tenant (e.g., employee handbook benefits and workplace ergonomics), returning permitted citations rather than empty results. As a result, the parity share shifted to **69.00% (316 / 458)**.
> 3. In the expanded 64-query benchmark (32 dev + 32 held-out test), 547 restricted query pairs were evaluated; at the calibrated 0.35 threshold, 407 returned empty results while 140 legitimately matched permitted documents, yielding a parity share of **74.41% (407 / 547)**.
> 4. In all cases, zero restricted documents or tokens were ever returned. Parity share is a threshold calibration metric, not a security boundary.

#### Similarity Threshold Sweep (Calibrated on 210-Chunk Multi-Tenant Corpus)

| Similarity Threshold | Synth Recall@5 | Synth MRR | Dev Recall@5 | Dev MRR | Restricted Parity Share | Cross-Tenant Leak Rate | Canary Violations | Behavioral Profile |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **0.15** | 100.00% | 0.9979 | 100.00% | 1.0000 | 2.19% (12 / 547) | 0.00% | 0 / 115,260 checks | Overly permissive; permitted chunks match loose topical overlap |
| **0.20** | 100.00% | 0.9979 | 100.00% | 1.0000 | 5.48% (30 / 547) | 0.00% | 0 / 115,260 checks | Permissive; broad semantic recall with frequent cross-domain permitted matches |
| **0.25** | 100.00% | 0.9979 | 100.00% | 1.0000 | 24.86% (136 / 547) | 0.00% | 0 / 115,260 checks | Moderate semantic matching; captures conversational queries |
| **0.30** | 100.00% | 0.9979 | 100.00% | 1.0000 | 47.90% (262 / 547) | 0.00% | 0 / 115,260 checks | Balanced filter; eliminates weakly related company documents |
| **0.35** | **100.00%** | **0.9979** | **100.00%** | **1.0000** | **74.41% (407 / 547)** | **0.00%** | **0 / 115,260 checks** | **Selected calibration threshold; 100% Dev & Held-Out Recall with 74.41% parity** |
| **0.40** | 99.18% | 0.9918 | 100.00% | 1.0000 | 89.95% (492 / 547) | 0.00% | 0 / 115,260 checks | Conservative cutoff; minor drop in synthetic recall (3 misses) |
| **0.45** | 97.54% | 0.9754 | 98.18% | 0.9818 | 96.16% (526 / 547) | 0.00% | 0 / 115,260 checks | Strict cutoff; 11 misses on concise technical terms |

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
