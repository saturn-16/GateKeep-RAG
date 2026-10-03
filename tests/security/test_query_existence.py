from fastapi.testclient import TestClient

from app.main import app


def _token(client: TestClient, username: str) -> str:
    return client.post("/v1/auth/login", json={"username": username, "password": username}).json()["access_token"]


def test_restricted_only_and_no_results_have_same_response_shape() -> None:
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_token(client, 'dave')}"}
    restricted = client.post("/v1/query", headers=headers, json={"question": "salary band engineers"})
    absent = client.post("/v1/query", headers=headers, json={"question": "topic with no matching document"})
    assert restricted.status_code == absent.status_code == 200
    restricted_body = restricted.json()
    absent_body = absent.json()
    assert set(restricted_body) == {"answer", "citations", "audit_id"} == set(absent_body)
    assert restricted_body["answer"] == absent_body["answer"]
    assert restricted_body["citations"] == absent_body["citations"] == []
    assert "restricted" not in str(restricted_body).lower()
    assert "hidden" not in str(restricted_body).lower()


def test_restricted_query_parity_at_calibrated_threshold() -> None:
    from app.config import get_settings
    settings = get_settings()
    orig = settings.retrieval_score_threshold
    settings.retrieval_score_threshold = 0.35
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {_token(client, 'dave')}"}
        # Dave asks about compensation benchmark base pay (target is restricted salary bands)
        resp = client.post("/v1/query", headers=headers, json={"question": "compensation benchmark base pay"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["citations"] == []
        assert data["answer"] == "I don't have access to information that answers this."
    finally:
        settings.retrieval_score_threshold = orig