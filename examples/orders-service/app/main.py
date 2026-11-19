"""HTTP surface required by the platform contract:

/healthz  liveness  - the process is up (never touches dependencies)
/readyz   readiness - queue and table resolved and the worker loop is polling
/metrics  Prometheus text format, scraped by Grafana Alloy
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import boto3
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import metrics
from app.config import Settings
from app.worker import OrderWorker

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("orders-service")


def default_worker(settings: Settings) -> OrderWorker:
    """Build the worker from the ambient AWS configuration.

    On EKS the pod-identity webhook injects AWS_ROLE_ARN + AWS_WEB_IDENTITY_TOKEN_FILE;
    locally the platform chart injects the same variables plus AWS_ENDPOINT_URL. Either
    way boto3 assumes the service's IRSA role with no code differences.
    """
    session = boto3.session.Session()
    identity = session.client("sts").get_caller_identity()
    log.info("running as %s (account %s)", identity["Arn"], identity["Account"])
    table = session.resource("dynamodb").Table(settings.table_name)
    return OrderWorker(settings, session.client("sqs"), table)


def create_app(
    settings: Settings | None = None,
    worker_factory: Callable[[Settings], Any] = default_worker,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or Settings.from_env()
        log.info(
            "starting %s version=%s env=%s fail_rate=%s",
            cfg.service,
            cfg.version,
            cfg.environment,
            cfg.fail_rate,
        )
        worker = worker_factory(cfg)
        worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(title="orders-service", lifespan=lifespan)

    @app.middleware("http")
    async def count_requests(request: Request, call_next):
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        metrics.HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str]:
        if app.state.worker.ready:
            return {"status": "ready"}
        response.status_code = 503
        return {"status": "not ready"}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
