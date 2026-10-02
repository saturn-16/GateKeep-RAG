from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def token(username: str, password: str) -> str:
    response = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_role_and_tenant_aware_query_flow() -> None:
    bob = token("bob", "bob")
    dave = token("dave", "dave")
    bob_result = client.post("/v1/query", headers={"Authorization": f"Bearer {bob}"}, json={"question": "salary band engineers"})
    dave_result = client.post("/v1/query", headers={"Authorization": f"Bearer {dave}"}, json={"question": "salary band engineers"})
    assert bob_result.status_code == 200
    assert "salary-acme" in {item["chunk_id"] for item in bob_result.json()["citations"]}
    assert "salary-globex" not in str(bob_result.json())
    assert "salary-acme" not in {item["chunk_id"] for item in dave_result.json()["citations"]}


def test_tenant_id_in_body_does_not_override_identity() -> None:
    token_value = token("bob", "bob")
    response = client.post("/v1/query", headers={"Authorization": f"Bearer {token_value}"}, json={"question": "salary band", "tenant_id": "globex-inc", "roles": ["admin"]})
    assert response.status_code == 200
    assert "salary-globex" not in str(response.json())
