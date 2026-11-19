"""Health and metrics contract. The platform chart's probes and Alloy depend on these."""

from fastapi.testclient import TestClient

from app.main import create_app


class FakeWorker:
    def __init__(self, ready: bool):
        self.ready = ready
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def client(settings, ready=True):
    worker = FakeWorker(ready)
    return TestClient(create_app(settings, worker_factory=lambda _: worker)), worker


def test_liveness_ignores_dependencies(settings):
    c, _ = client(settings, ready=False)
    with c:
        assert c.get("/healthz").status_code == 200


def test_readiness_follows_worker(settings):
    for ready, code in [(True, 200), (False, 503)]:
        c, _ = client(settings, ready=ready)
        with c:
            assert c.get("/readyz").status_code == code


def test_metrics_expose_platform_contract(settings):
    c, worker = client(settings)
    with c:
        c.get("/healthz")
        body = c.get("/metrics").text
    assert 'http_requests_total{method="GET",path="/healthz",status="200"}' in body
    assert 'app_work_items_total{outcome="failure"}' in body
    assert "app_work_duration_seconds_bucket" in body
    assert worker.started and worker.stopped
