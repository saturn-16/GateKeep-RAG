"""Run live API leakage checks and print PASS/FAIL."""

from fastapi.testclient import TestClient

from app.main import app


def token(client: TestClient, username: str) -> str:
    response = client.post("/v1/auth/login", json={"username": username, "password": username})
    response.raise_for_status()
    return response.json()["access_token"]


client = TestClient(app)
bob = client.post("/v1/query", headers={"Authorization": f"Bearer {token(client, 'bob')}"}, json={"question": "salary band engineers"}).json()
dave = client.post("/v1/query", headers={"Authorization": f"Bearer {token(client, 'dave')}"}, json={"question": "salary band engineers"}).json()
frank = client.post("/v1/query", headers={"Authorization": f"Bearer {token(client, 'frank')}"}, json={"question": "salary band engineers"}).json()

checks = {
    "hr sees Acme salary": any(item["chunk_id"].startswith("acme-corp:") or item["chunk_id"] == "salary-acme" for item in bob["citations"]),
    "employee cannot see restricted salary": all("salary-bands-2026" not in item["doc_id"] for item in dave["citations"]),
    "Globex cannot see Acme": all(not item["chunk_id"].startswith("acme-corp:") for item in frank["citations"]),
    "response has no hidden-document hint": "restricted" not in dave["answer"].lower() and "hidden" not in dave["answer"].lower(),
}
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
if not all(checks.values()):
    raise SystemExit(1)
