"""SQS -> DynamoDB worker.

Outcomes (app_work_items_total{outcome}):
  success  - stored in DynamoDB, message deleted
  rejected - malformed order; deleted (retrying cannot fix it) and logged
  failure  - processing error; message left on the queue to be retried after the
             visibility timeout. This is what the rollout analysis gates on.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any

from app import metrics
from app.config import Settings
from app.orders import InvalidOrder, build_order_record

log = logging.getLogger(__name__)


class InjectedFault(RuntimeError):
    """Raised when FAIL_RATE fault injection triggers (rollback demo)."""


class OrderWorker:
    def __init__(
        self,
        settings: Settings,
        sqs: Any,
        table: Any,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings
        self._sqs = sqs
        self._table = table
        self._rng = rng
        self._queue_url: str | None = None
        self._last_poll: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle -----------------------------------------------------------------------
    def resolve(self) -> None:
        """Look up the queue URL and confirm the table exists (fails fast on bad IAM)."""
        self._queue_url = self._sqs.get_queue_url(QueueName=self._settings.queue_name)["QueueUrl"]
        self._table.load()  # DescribeTable
        log.info("resolved queue=%s table=%s", self._queue_url, self._settings.table_name)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="order-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def ready(self) -> bool:
        """Ready once resources resolved and the poll loop is alive."""
        stale_after = self._settings.poll_wait_seconds * 3 + 5
        return self._queue_url is not None and (time.monotonic() - self._last_poll) < stale_after

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._queue_url is None:
                    self.resolve()
                self.poll_once()
            except Exception:  # keep the loop alive; readiness reflects the outage
                log.exception("poll failed")
                self._stop.wait(2)

    # ---- work ----------------------------------------------------------------------------
    def poll_once(self) -> int:
        resp = self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._settings.max_messages,
            WaitTimeSeconds=self._settings.poll_wait_seconds,
        )
        self._last_poll = time.monotonic()
        messages = resp.get("Messages", [])
        for msg in messages:
            self.handle(msg)
        return len(messages)

    def handle(self, msg: dict[str, Any]) -> str:
        start = time.perf_counter()
        outcome = "failure"
        try:
            try:
                record = build_order_record(json.loads(msg["Body"]), self._settings.version)
            except (InvalidOrder, json.JSONDecodeError) as exc:
                outcome = "rejected"
                log.warning("rejected message %s: %s", msg.get("MessageId"), exc)
                self._delete(msg)
                return outcome
            if self._rng() < self._settings.fail_rate:
                raise InjectedFault(f"injected fault (FAIL_RATE={self._settings.fail_rate})")
            self._table.put_item(Item=record)
            self._delete(msg)
            outcome = "success"
            log.info("stored order %s total=%s", record["orderId"], record["totalCents"])
            return outcome
        except Exception:
            log.exception("failed to process message %s", msg.get("MessageId"))
            return outcome
        finally:
            metrics.WORK_ITEMS.labels(outcome=outcome).inc()
            metrics.WORK_DURATION.observe(time.perf_counter() - start)

    def _delete(self, msg: dict[str, Any]) -> None:
        self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=msg["ReceiptHandle"])
