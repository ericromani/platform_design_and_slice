#!/usr/bin/env python3
"""Local demo helper for the orders-service slice (talks to LocalStack on localhost).

  orders_traffic.py send   --env staging --count 20 [--rate 2] [--duration 120]
  orders_traffic.py verify --env staging --expect 20
  orders_traffic.py iam    --env staging      # print the service role's effective policies
  orders_traffic.py clean-retained            # LocalStack only: drop tables a decommission retained

`send` with --duration keeps a steady stream flowing, which a rollout's analysis needs
to have data to judge (make break-and-rollback runs it in the background).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import boto3

ACCOUNTS = {"staging": "111111111111", "prod": "222222222222"}
SERVICE = "orders-service"


def client(kind: str, env: str):
    return boto3.client(
        kind,
        endpoint_url="http://localhost:4566",
        region_name="us-east-1",
        aws_access_key_id=ACCOUNTS[env],
        aws_secret_access_key="test",
    )


def order(i: int, run: str) -> dict:
    return {
        "orderId": f"{run}-{i:04d}",
        "customerId": f"cust-{i % 7}",
        "items": [
            {"sku": "TEA", "quantity": 1 + i % 3, "unitPriceCents": 450},
            {"sku": "CAKE", "quantity": 1, "unitPriceCents": 300},
        ],
    }


def cmd_send(a: argparse.Namespace) -> None:
    sqs = client("sqs", a.env)
    url = sqs.get_queue_url(QueueName=f"{SERVICE}-orders")["QueueUrl"]
    run = a.run or uuid.uuid4().hex[:6]
    sent, deadline = 0, time.monotonic() + a.duration
    while sent < a.count or time.monotonic() < deadline:
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps(order(sent, run)))
        sent += 1
        time.sleep(1 / a.rate)
    print(f"sent {sent} orders (run {run}) to {url}")


def cmd_verify(a: argparse.Namespace) -> None:
    table = boto3.resource(
        "dynamodb",
        endpoint_url="http://localhost:4566",
        region_name="us-east-1",
        aws_access_key_id=ACCOUNTS[a.env],
        aws_secret_access_key="test",
    ).Table(f"{SERVICE}-orders")
    deadline = time.monotonic() + a.timeout
    while True:
        items = table.scan()["Items"]
        if len(items) >= a.expect or time.monotonic() > deadline:
            break
        time.sleep(2)
    by_version: dict[str, int] = {}
    for it in items:
        by_version[it["processedBy"]] = by_version.get(it["processedBy"], 0) + 1
    print(f"{len(items)} orders in {SERVICE}-orders ({a.env}); processed by version: {by_version}")
    if items:
        sample = sorted(items, key=lambda i: i["processedAt"])[-1]
        print("latest:", json.dumps(sample, default=str))
    if len(items) < a.expect:
        sys.exit(f"expected at least {a.expect} orders")


def cmd_iam(a: argparse.Namespace) -> None:
    iam = client("iam", a.env)
    role = f"{SERVICE}-{a.env}"
    r = iam.get_role(RoleName=role)["Role"]
    print(f"role {r['Arn']}")
    print(f"  boundary: {r.get('PermissionsBoundary', {}).get('PermissionsBoundaryArn', 'none')}")
    print(f"  trust:    {json.dumps(r['AssumeRolePolicyDocument']['Statement'][0]['Condition'])}")
    for p in iam.list_attached_role_policies(RoleName=role)["AttachedPolicies"]:
        v = iam.get_policy(PolicyArn=p["PolicyArn"])["Policy"]["DefaultVersionId"]
        doc = iam.get_policy_version(PolicyArn=p["PolicyArn"], VersionId=v)["PolicyVersion"]["Document"]
        for s in doc["Statement"]:
            print(f"  {p['PolicyName']}: {s['Action']} on {s['Resource']}")


def cmd_clean_retained(a: argparse.Namespace) -> None:
    """Delete <service>-* DynamoDB tables left behind by a decommission (deletionPolicy=retain).

    Local convenience so `make demo` can be re-run: LocalStack Community cannot complete
    ACK's adoption of an existing table (no GetResourcePolicy), which works on AWS.
    """
    for env in ACCOUNTS:
        ddb = client("dynamodb", env)
        for name in ddb.list_tables()["TableNames"]:
            if name.startswith(f"{SERVICE}-"):
                # Tables are created with deletion protection; lift it first, as
                # decommission --delete-data does on AWS.
                ddb.update_table(TableName=name, DeletionProtectionEnabled=False)
                ddb.delete_table(TableName=name)
                print(f"deleted retained table {name} in {env} ({ACCOUNTS[env]})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send")
    s.add_argument("--env", default="staging", choices=ACCOUNTS)
    s.add_argument("--count", type=int, default=20)
    s.add_argument("--rate", type=float, default=5.0, help="messages per second")
    s.add_argument("--duration", type=float, default=0, help="keep sending for N seconds")
    s.add_argument("--run", help="order id prefix")
    s.set_defaults(fn=cmd_send)
    v = sub.add_parser("verify")
    v.add_argument("--env", default="staging", choices=ACCOUNTS)
    v.add_argument("--expect", type=int, default=1)
    v.add_argument("--timeout", type=float, default=60)
    v.set_defaults(fn=cmd_verify)
    i = sub.add_parser("iam")
    i.add_argument("--env", default="staging", choices=ACCOUNTS)
    i.set_defaults(fn=cmd_iam)
    c = sub.add_parser("clean-retained")
    c.set_defaults(fn=cmd_clean_retained)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
