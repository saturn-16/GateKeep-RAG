from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoints() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
