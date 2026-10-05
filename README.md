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

### Security Results & Invariants

All security properties are verified against live PostgreSQL 16 and Qdrant 1.19.1 backends on an isolated multi-tenant corporate corpus:

1. **Every-Principal Counterfactual Invariance with True Removal (Corpus size: 210 chunks across 3 tenants)**
   - **Evaluation Methodology**: For all **4,972 principal-query pairs** evaluated across 11 personas and 3 tenants (Corpus size: 210 chunks, 3 tenants), queries were executed in **World 1** (baseline corpus with restricted documents present) and **World 2** (TRUE REMOVAL: for each principal, every document they are not authorized to access was physically deleted from both PostgreSQL and Qdrant).
   - **Permitted Document Retrieval**: In **3,585 pairs** (Corpus size: 210 chunks), authorized users retrieved permitted citations; citation IDs, ordering, scores (within $10^{-4}$ tolerance), and answers were identical between World 1 and World 2.
   - **Restricted / Unmatched Retrieval**: In **1,387 pairs** (Corpus size: 210 chunks), unauthorized users received the standard refusal (`citations: []`, identical refusal answer).
   - **Result**: **0 mismatches** across all 4,972 evaluations (100.0% counterfactual invariance rate; Corpus size: 210 chunks). The presence or physical deletion of restricted documents produces zero observational or behavioral divergence.

2. **Canary Token Defense (Corpus size: 210 chunks across 3 tenants)**
   - **CSPRNG Generation**: A unique canary token (`CANARY_<HEX16>_<TENANT>_<DOC>_C<IDX>`, 128 bits of CSPRNG entropy via Python `secrets.token_hex(16)`) was seeded into **all 210 chunks** of the corpus (Corpus size: 210 chunks).
   - **Four-Location Inspection**: For every unauthorized query evaluation, 4 distinct locations were inspected:
     1. Prompt string and context passed to the LLM backend (intercepted via `PromptCapturingLLM`)
     2. Generated LLM answer text
     3. Structured citations list
     4. Serialized HTTP response JSON payload
   - **Result**: $1,823 \text{ unauthorized user-chunk pairs} \times 452 \text{ unique queries} = \mathbf{823,996} \text{ canary checks}$ ($\mathbf{3,295,984}$ location inspections; Corpus size: 210 chunks). **0 canary violations detected (0.00% leak rate)**.

3. **Threshold-Independence at Threshold 0.00 (Corpus size: 210 chunks across 3 tenants)**
   - When the similarity score threshold is set to `0.00` (allowing every query to retrieve the top-5 permitted chunks regardless of similarity score; Corpus size: 210 chunks), cross-tenant leak rate remains **0.00%** (0 leaks across 4,972 pairs) and canary violations remain **0 / 823,996 checks** (verified in `tests/security/test_threshold_independence.py`). Access control operates at the vector pre-filter and relational verification layers, independent of the similarity score threshold.

4. **Role-Condition Mutation Testing (Corpus size: 210 chunks across 3 tenants)**
   - When the role filter condition is mutated/removed from `build_filter(principal)` in `src/app/rag/vectorstore/tenant_scoped_retriever.py`, the live counterfactual test immediately fails with real divergence assertions showing unauthorized chunks retrieved into World 1 candidate sets.

5. **Cryptographic Audit Hash Chain (Corpus size: 210 chunks across 3 tenants)**
   - Audit records are signed with SHA-256 chaining per tenant, protected with PostgreSQL transaction advisory locks (`pg_advisory_xact_lock`) and dedicated non-owner role privileges (`gatekeep_app`). Verification is performed via `/v1/audit/verify`.

6. **Non-Owner Database Role & Least Privilege**
   - The runtime API service connects using the unprivileged `gatekeep_app` database role, which possesses `SELECT`, `INSERT` on app tables, and row-level trigger constraints preventing `UPDATE` or `DELETE` on `audit_logs`. Database migrations and administrative tasks execute under a separate owner role.

---

## Retrieval evaluation (preliminary)

The evaluation corpus is small and synthetic (210 chunks across 3 tenants, 30 documents). Hand-written queries were written by an AI that had access to the corpus. Empirical testing indicates that the dense-retrieval-plus-threshold setup cannot reliably reject unanswerable questions on this corpus (at similarity threshold 0.35, 88.89% of unanswerable queries return permitted chunks with weak semantic overlap instead of being rejected). Retrieval quality is a separate concern from the security properties and is future work (hybrid search combining candidate-scoped BM25 with dense embeddings, and a larger blind human-written query set).

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

## Limitations and Future Work

1. **Timing Side Channels**: Vector search and relational verification execution times vary based on candidate counts and database index operations. The system does not enforce constant-time query responses.
2. **Database Superuser Audit Bypass**: A PostgreSQL superuser or database owner with direct root access can bypass trigger constraints and mutate audit rows directly. However, any external modification breaks the cryptographic SHA-256 hash chain, which will be detected during integrity verification via `/v1/audit/verify`.
3. **Single Region Deployment**: The service currently deploys in a single region; multi-region data replication, geographic tenant pinning, and cross-region consensus are not yet supported.
4. **Demo Credentials & Static Passwords**: Default seeded persona credentials (`alice`, `bob`, `dave`, etc.) and default docker-compose passwords must be replaced with dynamically rotated credentials managed by a dedicated secrets manager in production environments.
5. **No Enterprise SSO**: Authentication relies on local JWT tokens and database-backed password hashes. Enterprise identity providers (OIDC, SAML 2.0, SCIM directory synchronization) are not implemented.
6. **Small Synthetic Corpus**: The active benchmark corpus consists of 210 chunks across 3 tenants with 30 document templates. Real-world corporate deployments involve significantly larger, messier, and unstructured corpora.
7. **Preliminary Retrieval Evaluation**: Retrieval quality evaluation is preliminary. Dense retrieval with cosine thresholding struggles to reliably reject unanswerable queries on this corpus. Evaluating hybrid search (candidate-scoped BM25 + dense) against a larger blind human-written query set is future work.

---

## Resume Bullet Variants

### Variant 1: Security & Distributed Systems Focus
> Architected a permission-aware multi-tenant RAG platform using FastAPI, PostgreSQL, and Qdrant, enforcing defense-in-depth with vector pre-filtering, relational ACL re-verification, and an append-only SHA-256 audit hash chain, achieving 0.00% cross-tenant data leakage across an evaluation benchmark.

### Variant 2: Full-Stack AI & Infrastructure Focus
> Engineered an enterprise RAG service featuring dual vector/relational access control, local embedding models (`all-MiniLM-L6-v2`), and local LLM integration (`llama3.2:3b`), paired with an interactive React audit and side-by-side role comparison frontend and CI/CD pipelines incorporating pip-audit and gitleaks scanning.

### Variant 3: Security & Verification Focus
> Designed and executed an expanded adversarial security evaluation suite measuring multi-tenant RAG isolation, validating 0.00% cross-tenant data leakage, 100.00% counterfactual invariance across 4,972 principal-query pairs with physical document deletion, and 823,996 canary token inspections with zero violations across 210 corpus chunks.
