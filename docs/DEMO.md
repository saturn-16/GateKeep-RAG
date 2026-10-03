# GateKeep RAG Demo Walkthrough

## 1. Quickstart & Service Launch

1. Launch backend services (PostgreSQL 16 and Qdrant 1.19.1):
   ```bash
   docker compose up -d --build
   ```
2. Run database migrations:
   ```bash
   alembic upgrade head
   ```
3. Run the live API service:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

---

## 2. Seeded User Personas

| Username | Password | Tenant | Roles | Clearance | Description |
|---|---|---|---|---|---|
| `alice` | `alice` | `acme-corp` | `admin` | `restricted` | Acme Tenant Administrator |
| `bob` | `bob` | `acme-corp` | `hr` | `restricted` | Acme HR Specialist (can see salaries) |
| `carol` | `carol` | `acme-corp` | `finance` | `confidential` | Acme Finance Analyst |
| `dave` | `dave` | `acme-corp` | `employee` | `internal` | Acme General Employee (no salary access) |
| `frank` | `frank` | `globex-inc` | `admin` | `restricted` | Globex Tenant Administrator |

---

## 3. Permission Isolation Verification

### Step A: Login as Bob (Acme HR)
```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "bob", "password": "bob"}'
```
*Ask about salary:*
```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer <BOB_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the salary band for engineers?"}'
```
**Result:** Returns Acme salary citations (`salary-acme`, `acme-corp:salary-bands-2026:chunk-0`) with salary data.

### Step B: Login as Dave (Acme Employee)
```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "dave", "password": "dave"}'
```
*Ask the exact same question:*
```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer <DAVE_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the salary band for engineers?"}'
```
**Result:** Dave receives zero citations (`"citations": []`) and the standard no-access response: `"I don't have access to information that answers this."` No restricted metadata or content leaks.

### Step C: Cross-Tenant Isolation with Frank (Globex Admin)
```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "frank", "password": "frank"}'
```
*Ask about salary:*
```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer <FRANK_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the salary band for engineers?"}'
```
**Result:** Frank only receives Globex documents (`globex-inc:salary-bands-2026:0`). Never sees Acme documents even though Frank is an admin.

---

## 4. Ollama Local LLM Smoke Test (`llama3.2:3b`)

GateKeep RAG defaults to `MockLLM` for fast, deterministic, reproducible testing without GPU/model download overhead.

To use local Ollama with `llama3.2:3b`:

1. Ensure Ollama is running and has the model pulled:
   ```bash
   ollama pull llama3.2:3b
   ollama list
   ```

2. Run the API with Ollama configured:
   ```bash
   LLM_PROVIDER=ollama LLM_MODEL=llama3.2:3b uvicorn app.main:app
   ```

3. Run the end-to-end Ollama automated smoke test:
   ```bash
   pytest tests/integration/test_ollama_smoke.py -v
   ```

**Verified Behavior with Ollama (`llama3.2:3b`):**
- Bob's query returns synthesized prose with grounded citations: `[acme-corp:salary-bands-2026:chunk-0] The salary band for engineers is 145,000.`
- Output guard validates that all cited chunk IDs exist in verified context.
- Dave's restricted query returns `"I don't have access to information that answers this."` with zero citations.
