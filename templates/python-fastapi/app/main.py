"""HTTP surface required by the platform contract (do not remove):

/healthz  liveness  - the process is up; never checks dependencies
/readyz   readiness - dependencies reachable; return 503 until they are
/metrics  Prometheus text format, scraped by Grafana Alloy
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import metrics
from app.work import Rejected, process, record

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("__SERVICE_NAME__")


def dependencies_ready() -> bool:
    # TODO: check what your service needs (e.g. sqs.get_queue_url, table.load()) and cache
    # the result briefly. AWS coordinates arrive as env vars, e.g. SQS_<NAME>_QUEUE_NAME.
    return True


def create_app() -> FastAPI:
    app = FastAPI(title="__SERVICE_NAME__")

    @app.middleware("http")
    async def count_requests(request: Request, call_next):
        response = await call_next(request)
        path = getattr(request.scope.get("route"), "path", "unmatched")
        metrics.HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str]:
        if dependencies_ready():
            return {"status": "ready"}
        response.status_code = 503
        return {"status": "not ready"}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/work")
    def work(item: dict[str, Any]) -> dict[str, Any]:
        try:
            return record(lambda: process(item))
        except Rejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
