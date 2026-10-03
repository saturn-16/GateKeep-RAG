import os
import urllib.request
import pytest
from fastapi.testclient import TestClient

from app.api.state import state
from app.config import get_settings
from app.main import app
from app.rag.llm import MockLLM, OllamaLLM

pytestmark = pytest.mark.real_stack


def is_ollama_ready() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


@pytest.mark.skipif(
    os.getenv("RUN_REAL_STACK") != "1" or not is_ollama_ready(),
    reason="requires running Ollama instance with llama3.2:3b",
)
def test_ollama_end_to_end_smoke() -> None:
    settings = get_settings()
    previous_llm = state.llm
    try:
        state.llm = OllamaLLM(model="llama3.2:3b", url="http://localhost:11434/api/generate")
        client = TestClient(app)

        # 1. Bob (HR) can ask about salaries and receives grounded answer + citation
        bob_token = client.post("/v1/auth/login", json={"username": "bob", "password": "bob"}).json()["access_token"]
        bob_resp = client.post(
            "/v1/query",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"question": "What is the salary band for engineers?"},
        )
        assert bob_resp.status_code == 200
        bob_data = bob_resp.json()
        assert len(bob_data["citations"]) > 0
        assert all("acme-corp" in c["doc_id"] or "salary-acme" in c["chunk_id"] for c in bob_data["citations"])

        # 2. Dave (Employee) asking the same question gets no citations and no-access response
        dave_token = client.post("/v1/auth/login", json={"username": "dave", "password": "dave"}).json()["access_token"]
        dave_resp = client.post(
            "/v1/query",
            headers={"Authorization": f"Bearer {dave_token}"},
            json={"question": "What is the salary band for engineers?"},
        )
        assert dave_resp.status_code == 200
        dave_data = dave_resp.json()
        assert dave_data["citations"] == []
        assert dave_data["answer"] == "I don't have access to information that answers this."

        # 3. Frank (Globex Admin) asking gets only Globex documents, never Acme
        frank_token = client.post("/v1/auth/login", json={"username": "frank", "password": "frank"}).json()["access_token"]
        frank_resp = client.post(
            "/v1/query",
            headers={"Authorization": f"Bearer {frank_token}"},
            json={"question": "What is the salary band for engineers?"},
        )
        assert frank_resp.status_code == 200
        frank_data = frank_resp.json()
        assert all("globex" in c["doc_id"] or "globex" in c["chunk_id"] for c in frank_data["citations"])
    finally:
        state.llm = previous_llm
