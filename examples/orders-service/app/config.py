"""Runtime configuration, read from the environment the platform chart injects.

The chart derives these names from deploy/values-<env>.yaml:
  aws.sqs[name=orders]      -> SQS_ORDERS_QUEUE_NAME
  aws.dynamodb[name=orders] -> DYNAMODB_ORDERS_TABLE
plus PLATFORM_SERVICE / PLATFORM_ENVIRONMENT / PLATFORM_VERSION and the AWS_* SDK settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service: str
    environment: str
    version: str
    queue_name: str
    table_name: str
    # Fault injection for the rollback demo: fraction of messages that fail processing.
    fail_rate: float
    poll_wait_seconds: int
    max_messages: int

    @classmethod
    def from_env(cls) -> Settings:
        fail_rate = float(os.environ.get("FAIL_RATE", "0"))
        if not 0.0 <= fail_rate <= 1.0:
            raise ValueError(f"FAIL_RATE must be within [0, 1], got {fail_rate}")
        return cls(
            service=os.environ.get("PLATFORM_SERVICE", "orders-service"),
            environment=os.environ.get("PLATFORM_ENVIRONMENT", "dev"),
            version=os.environ.get("PLATFORM_VERSION", "dev"),
            queue_name=os.environ["SQS_ORDERS_QUEUE_NAME"],
            table_name=os.environ["DYNAMODB_ORDERS_TABLE"],
            fail_rate=fail_rate,
            poll_wait_seconds=int(os.environ.get("POLL_WAIT_SECONDS", "10")),
            max_messages=int(os.environ.get("MAX_MESSAGES", "10")),
        )
