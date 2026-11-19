"""Integration tests against LocalStack (real AWS APIs, no account needed).

The central build runs these with a LocalStack service container. Locally:
  LOCALSTACK_ENDPOINT=http://localhost:4566 pytest -m integration
"""

import os
import uuid

import boto3
import pytest

ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ENDPOINT, reason="LOCALSTACK_ENDPOINT not set"),
]


@pytest.fixture
def session():
    # A throwaway LocalStack account, isolated from anything deployed locally.
    return boto3.session.Session(
        aws_access_key_id="000000000099", aws_secret_access_key="test", region_name="us-east-1"
    )


def test_aws_round_trip(session):
    # TODO: replace with your service's real flow (e.g. send to your queue, run one poll,
    # assert the table row). This smoke test proves the SDK wiring against LocalStack.
    sqs = session.client("sqs", endpoint_url=ENDPOINT)
    url = sqs.create_queue(QueueName=f"it-{uuid.uuid4().hex[:8]}")["QueueUrl"]
    try:
        sqs.send_message(QueueUrl=url, MessageBody="ping")
        msgs = sqs.receive_message(QueueUrl=url, WaitTimeSeconds=1).get("Messages", [])
        assert [m["Body"] for m in msgs] == ["ping"]
    finally:
        sqs.delete_queue(QueueUrl=url)
