"""End-to-end against LocalStack: real SQS + DynamoDB APIs, real boto3 wire calls.

Runs in the central build workflow (LocalStack service container) and locally with:
  LOCALSTACK_ENDPOINT=http://localhost:4566 pytest -m integration
Uses its own throwaway account (000000000099) so it never touches deployed resources.
"""

import json
import os
import uuid

import boto3
import pytest

from app.config import Settings
from app.worker import OrderWorker
from tests.conftest import order_message

ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ENDPOINT, reason="LOCALSTACK_ENDPOINT not set"),
]


@pytest.fixture
def session():
    return boto3.session.Session(
        aws_access_key_id="000000000099", aws_secret_access_key="test", region_name="us-east-1"
    )


@pytest.fixture
def resources(session):
    name = f"orders-it-{uuid.uuid4().hex[:8]}"
    sqs = session.client("sqs", endpoint_url=ENDPOINT)
    ddb = session.resource("dynamodb", endpoint_url=ENDPOINT)
    url = sqs.create_queue(QueueName=name)["QueueUrl"]
    table = ddb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    yield name, sqs, url, table
    sqs.delete_queue(QueueUrl=url)
    table.delete()


def test_queue_to_table(resources):
    name, sqs, url, table = resources
    settings = Settings("orders-service", "it", "it-sha", name, name, 0.0, 1, 10)
    for i in range(3):
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps(order_message(f"it-{i}")))

    worker = OrderWorker(settings, sqs, table)
    worker.resolve()
    processed = 0
    for _ in range(5):
        processed += worker.poll_once()
        if processed >= 3:
            break

    assert processed == 3
    stored = {i["orderId"] for i in table.scan()["Items"]}
    assert stored == {"it-0", "it-1", "it-2"}
