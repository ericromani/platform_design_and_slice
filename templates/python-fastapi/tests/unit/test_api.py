"""Platform contract tests: probes and metrics must keep working. Keep these."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoints():
    with TestClient(create_app()) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 200


def test_metrics_contract():
    with TestClient(create_app()) as c:
        c.post("/work", json={"id": "1"})
        body = c.get("/metrics").text
    assert "http_requests_total" in body
    assert 'app_work_items_total{outcome="success"}' in body
