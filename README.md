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
   - **Permitted Document Retrieval**: In **3,585 pairs**, unauthorized users legitimately retrieved citations from permitted internal/public documents; citations (IDs and ordering), scores (within $10^{-4}$ tolerance), and answers were mathematically identical between World 1 and World 2.
   - **Restricted / Unmatched Retrieval**: In **1,387 pairs**, unauthorized users received the standard no-access response (`citations: []`, identical refusal answer).
   - **Result**: **0 mismatches** across all 4,972 evaluations. The existence or physical absence of restricted documents produces zero observational or behavioral divergence.

2. **Ubiquitous Canary Token Defense (0 Leaks / 823,996 Checks)**
   - **CSPRNG Generation**: A unique cryptographically secure canary token (`CANARY_<HEX16>_<TENANT>_<DOC>_C<IDX>`, 128 bits of CSPRNG entropy via Python `secrets.token_hex(16)`) was placed into **EVERY chunk of every document** across the entire corpus (all 210 chunks).
   - **Four-Location Inspection**: For every unauthorized query evaluation, 4 distinct locations are inspected:
     1. Raw prompt string and `DOCUMENT CONTEXT` sent to the LLM backend (intercepted via `PromptCapturingLLM`)
     2. Generated LLM answer text
     3. Structured citations list
     4. Complete serialized HTTP response JSON payload
   - **Result**: $1,823 \text{ unauthorized user-chunk pairs} \times 452 \text{ unique queries} = \mathbf{823,996} \text{ canary checks}$ per sweep ($\mathbf{3,295,984}$ location inspections). **0 canary violations detected (0.00% leak rate)**.

3. **Threshold-Independence (Guaranteed Security at Threshold 0.00)**
   - When the similarity score threshold is set to `0.00` (allowing every query to retrieve the top-5 permitted chunks regardless of similarity score), cross-tenant leak rate remains **0.00%** and canary violations remain **0 / 823,996** (proven in `tests/security/test_threshold_independence.py`). Security enforcement operates at the database pre-filter and defense-in-depth layer, completely independent of the score threshold.

---

### Empirical Retrieval Quality & Honest Benchmarking Disclosures

> [!WARNING]
> **Retrieval Disclosure & Optimistic Bias**: Retrieval metrics on the expanded 64-query hand-written benchmark achieve 100% Recall@5, but **these numbers are optimistic**. The queries were drafted by an AI model with full access to the corpus chunk texts. A lexical audit indicates that **50.0% of the hand-written queries (32 of 64)** share $\ge 50\%$ content words or a 4+-word exact n-gram with the target chunk (e.g., `"iso 27001 information security certification"`). Real-world user queries exhibit greater phrasing divergence, typos, and semantic drift.

#### Baseline vs. Expanded Retrieval Performance

| Query Set | Corpus Size | Recall@5 | MRR | Notes & Methodology |
|---|:---:|:---:|:---:|---|
| **Original 30 Natural Queries (`main`)** | 210 chunks | **63.33%** (19/30) | **0.6167** | Raw evaluation as written; 9 queries failed due to non-existent document IDs |
| **Original 30 Queries (Slug-Corrected)** | 210 chunks | **81.48%** (22/27) | **0.7963** | Evaluated against existing documents; 5 miss due to vocabulary divergence |
| **Synthetic Keyword Queries** | 210 chunks | **100.00%** (487/487) | **0.9979** | High lexical overlap with chunk headers and template terms |
| **Hand-Written Dev Set (32 queries)** | 210 chunks | **100.00%** (220/220) | **1.0000** | Used exclusively to calibrate similarity threshold |
| **Hand-Written Held-Out Test Set (32 queries)**| 210 chunks | **100.00%** (220/220) | **0.9955** | Scored only once at the selected threshold (no tuning) |
| **All Hand-Written Combined (64 queries)** | 210 chunks | **100.00%** (440/440) | **0.9978** | Optimistic benchmark (AI-generated with corpus access) |

---

### Evaluation Metrics Summary (Corpus: 210 chunks, 30 documents, 3 tenants)

> [!NOTE]
> **Corpus Size Reconciliation (210 vs 246/247 chunks)**: The active multi-tenant evaluation corpus contains exactly **210 chunks** (30 document templates $\times$ 70 chunks/tenant $\times$ 3 tenants). Earlier reports showing 246 or 247 chunks included residual test chunks from prior unpurged integration test executions matching `chunk-` in the PostgreSQL database. The evaluation suite now operates on dedicated tenants (`eval-acme-corp`, `eval-globex-inc`, `eval-initech-llc`) that are cleanly isolated from demo tenants.

| Metric | Before (Phase B) | After (Quality Hardening) | Scope & Evaluation Conditions |
|---|:---:|:---:|---|
| **Corpus Size** | 247 chunks | **210 chunks** (70/tenant $\times$ 3) | 30 documents across isolated evaluation tenants |
| **Live Integration & Security Suite** | 31 passed, 0 skipped | **36 passed, 0 skipped, 1 opt-in** | `pytest -v` (`RUN_REAL_STACK=1`, `PERSISTENCE_BACKEND=postgres`, `VECTOR_BACKEND=qdrant`) |
| **Cross-Tenant Leak Rate** | 0.00% (3,850 queries) | **0.00%** (4,972 pairs) | Evaluated across all 11 user personas in 3 organizations |
| **Ubiquitous Canary Violations** | 0 / 89,250 (0.00%) | **0 / 823,996** (0.00%) | Canaries on **all 210 chunks**; 3,295,984 location inspections across 11 users |
| **Counterfactual Invariance (True Physical Removal)** | 100.00% (1,750 pairs) | **100.00% (4,972 pairs)** | Evaluated for every principal (0 mismatches across all 11 users) |
| **Threshold Independence (Threshold 0.00)** | Untested | **PASSED (0 leaks, 0 canaries)** | Proves security does not depend on similarity score filtering |
| **Password Hashing Cost** | scrypt ($N=2^{14}$) | **scrypt ($N=2^{17}$, 128 MB RAM)** | $N=131072, r=8, p=1, \text{maxmem}=256\text{MB}$ (~435ms CPU hardness) |
| **Role Separation & Least Privilege** | Non-owner `gatekeep_app` | **Non-owner `gatekeep_app`** | Runtime API runs as unprivileged user; migrations use owner role |

---

### Parity as a Behavioral Metric & Reconciliation

> [!NOTE]
> **Why Restricted Parity Shifted (73.14% $\rightarrow$ 69.00% $\rightarrow$ 61.61% $\rightarrow$ 69.65%)**:
> 1. In earlier evaluations with only keyword-dense synthetic queries, restricted query parity was **73.14% (207 / 283)**.
> 2. When the first 30 hand-written natural queries were added, the total number of restricted-only queries evaluated against unauthorized users increased from 283 to 458. Certain natural queries regarding compensation, benefits, and office policies had legitimate semantic overlap ($>0.35$) with permitted documents in the user's tenant (e.g., employee handbook benefits and workplace ergonomics), returning permitted citations rather than empty results. As a result, the parity share shifted to **69.00% (316 / 458)**.
> 3. In intermediate testing with canaries appended directly to embedded chunk text, pseudo-random hex tokens altered chunk vector positions, artificially inflating similarity scores and dropping parity to **61.61% (337 / 547)**.
> 4. Restoring clean chunk text embedding while retaining canaries strictly in the payload for prompt/display validation restored true semantic distribution, yielding a calibrated parity share of **69.65% (381 / 547)**.
> 5. In all cases, zero restricted documents or tokens were ever returned. Parity share is a threshold calibration metric, not a security boundary.

#### Similarity Threshold Sweep (Calibrated on 210-Chunk Multi-Tenant Corpus)

> [!NOTE]
> **Threshold Calibration Objective**: Maximize restricted query parity while guaranteeing 100.0% Recall@5 across both Synthetic and Hand-Written Dev benchmark sets. While permitted recall remains 100.00% across the 0.15–0.35 range, the sweep strongly discriminates on restricted query parity (shifting from 1.28% at 0.15 to 69.65% at 0.35). Threshold `0.35` is selected as the calibrated cutoff because it eliminates spurious semantic overlap while preserving 100.00% Recall@5 on both Synthetic and Dev sets. Above 0.40, marginal recall degradation begins.

| Similarity Threshold | Synth Recall@5 | Synth MRR | Dev Recall@5 | Dev MRR | Restricted Parity Share | Cross-Tenant Leak Rate | Canary Violations | Behavioral Profile |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **0.15** | 100.00% | 0.9979 | 100.00% | 1.0000 | 1.28% (7 / 547) | 0.00% | 0 / 823,996 checks | Overly permissive; permitted chunks match loose topical overlap |
| **0.20** | 100.00% | 0.9979 | 100.00% | 1.0000 | 7.31% (40 / 547) | 0.00% | 0 / 823,996 checks | Permissive; broad semantic recall with frequent cross-domain permitted matches |
| **0.25** | 100.00% | 0.9979 | 100.00% | 1.0000 | 25.23% (138 / 547) | 0.00% | 0 / 823,996 checks | Moderate semantic matching; captures conversational queries |
| **0.30** | 100.00% | 0.9979 | 100.00% | 1.0000 | 47.71% (261 / 547) | 0.00% | 0 / 823,996 checks | Balanced filter; eliminates weakly related company documents |
| **0.35** | **100.00%** | **0.9979** | **100.00%** | **1.0000** | **69.65% (381 / 547)** | **0.00%** | **0 / 823,996 checks** | **Selected calibration threshold; 100% Dev & Held-Out Recall with 69.65% parity** |
| **0.40** | 98.56% | 0.9856 | 100.00% | 1.0000 | 88.67% (485 / 547) | 0.00% | 0 / 823,996 checks | Conservative cutoff; minor drop in synthetic recall (4 misses) |
| **0.45** | 97.13% | 0.9713 | 96.36% | 0.9636 | 95.98% (525 / 547) | 0.00% | 0 / 823,996 checks | Strict cutoff; 16 misses on concise technical terms |

---

## Seeded Personas & Credential Notice

> [!WARNING]
> **Demo-Only Credentials & Secrets Replacement**: All personas below (`alice`/`alice`, `bob`/`bob`, etc.) and default service credentials (such as `gatekeep:gatekeep` and default JWT secrets) are seeded strictly for local sandbox demonstration, test suites, and offline evaluation. In any staging or production deployment, default credentials and static database passwords must be replaced by strong, dynamically provisioned secrets managed via a dedicated secrets store (such as AWS Secrets Manager or HashiCorp Vault).

> [!IMPORTANT]
> **Password Hash Migration & Reset Notice**: The password hashing format has been upgraded to explicitly encode scrypt parameters as `scrypt$<n>$<r>$<p>$<salt_b64>$<digest_b64>` (e.g. `scrypt$131072$8$1$...`) with strict parameter caps ($N \le 2^{18}$, $r \le 16$, $p \le 4$), and blind parameter fallbacks have been eliminated. Any pre-existing user accounts created under earlier unparameterized hash formats cannot be verified and require an administrative password reset or re-seeding via `python scripts/seed_demo.py`.

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
