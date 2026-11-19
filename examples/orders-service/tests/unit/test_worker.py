"""Worker behaviour against moto's in-memory SQS and DynamoDB."""

import json

import boto3
import pytest
from moto import mock_aws

from app import metrics
from app.worker import OrderWorker
from tests.conftest import order_message


@pytest.fixture
def aws(settings, monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        sqs = boto3.client("sqs")
        url = sqs.create_queue(QueueName=settings.queue_name)["QueueUrl"]
        ddb = boto3.resource("dynamodb")
        table = ddb.create_table(
            TableName=settings.table_name,
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield sqs, url, table


def count(outcome):
    return metrics.WORK_ITEMS.labels(outcome=outcome)._value.get()


def depth(sqs, url):
    attrs = sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return sum(int(v) for v in attrs.values())


def test_stores_order_and_deletes_message(settings, aws):
    sqs, url, table = aws
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps(order_message("o-42")))
    worker = OrderWorker(settings, sqs, table)
    worker.resolve()
    before = count("success")

    assert worker.poll_once() == 1

    item = table.get_item(Key={"orderId": "o-42"})["Item"]
    assert item["totalCents"] == 1200
    assert item["processedBy"] == "test-sha"
    assert depth(sqs, url) == 0
    assert count("success") == before + 1
    assert worker.ready


def test_malformed_message_is_rejected_and_deleted(settings, aws):
    sqs, url, table = aws
    sqs.send_message(QueueUrl=url, MessageBody="not json")
    worker = OrderWorker(settings, sqs, table)
    worker.resolve()
    before = count("rejected")

    worker.poll_once()

    assert count("rejected") == before + 1
    assert depth(sqs, url) == 0


def test_processing_failure_leaves_message_for_retry(settings, aws):
    sqs, url, table = aws
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps(order_message("o-7")))
    faulty = settings.__class__(**{**settings.__dict__, "fail_rate": 1.0})
    worker = OrderWorker(faulty, sqs, table, rng=lambda: 0.0)
    worker.resolve()
    before = count("failure")

    worker.poll_once()

    assert count("failure") == before + 1
    assert "Item" not in table.get_item(Key={"orderId": "o-7"})
    assert depth(sqs, url) == 1  # still there, invisible until the timeout expires
