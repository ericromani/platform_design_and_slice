"""Your service's unit of work. Replace the body of `process` with your logic.

Report every item through `record` so the platform's rollout analysis can judge new
releases: a canary whose failure ratio exceeds rollout.analysis.maxWorkFailureRatio is
rolled back automatically.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app import metrics


class Rejected(ValueError):
    """Bad input that retrying will never fix (counted as outcome="rejected")."""


def process(item: dict[str, Any]) -> dict[str, Any]:
    # TODO: implement your business logic. Raise Rejected for invalid input; any other
    # exception counts as a failure (and will fail a canary if it happens too often).
    if "id" not in item:
        raise Rejected("item needs an id")
    return {"id": item["id"], "status": "processed"}


def record(fn: Callable[[], Any]) -> Any:
    """Run fn, counting success / rejected / failure and its duration."""
    start = time.perf_counter()
    outcome = "failure"
    try:
        result = fn()
        outcome = "success"
        return result
    except Rejected:
        outcome = "rejected"
        raise
    finally:
        metrics.WORK_ITEMS.labels(outcome=outcome).inc()
        metrics.WORK_DURATION.observe(time.perf_counter() - start)
