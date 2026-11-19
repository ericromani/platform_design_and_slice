"""Static least-privilege proof for every IAM policy the platform can create.

LocalStack Community does not enforce IAM, so these tests are the guarantee: for each
kro RGD policy we extract the action list per access level and the Resource expression
straight from the CEL source, and assert that
  1. each access level grants exactly the documented actions (no drift, no extras),
  2. the Resource is only the RGD's own resource, never "*" or another resource,
  3. every action is allowed by the Terraform permissions boundary, so even a bad RGD
     edit cannot produce a role broader than the boundary.
(The e2e run additionally prints the live policies: `make iam`.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RGDS = ROOT / "platform" / "bootstrap" / "rgds"
BOUNDARY_TF = ROOT / "infra" / "terraform" / "modules" / "platform-iam" / "main.tf"

EXPECTED = {
    "platform-queue.yaml": {
        "consume": {
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:ChangeMessageVisibility",
            "sqs:GetQueueAttributes",
            "sqs:GetQueueUrl",
        },
        "publish": {"sqs:SendMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"},
        "consumepublish": {
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:ChangeMessageVisibility",
            "sqs:SendMessage",
            "sqs:GetQueueAttributes",
            "sqs:GetQueueUrl",
        },
    },
    "platform-table.yaml": {
        "read": {
            "dynamodb:GetItem",
            "dynamodb:BatchGetItem",
            "dynamodb:Query",
            "dynamodb:Scan",
            "dynamodb:DescribeTable",
        },
        "readwrite": {
            "dynamodb:GetItem",
            "dynamodb:BatchGetItem",
            "dynamodb:Query",
            "dynamodb:Scan",
            "dynamodb:DescribeTable",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
            "dynamodb:BatchWriteItem",
        },
    },
    "platform-topic.yaml": {"publish": {"sns:Publish", "sns:GetTopicAttributes"}},
    "platform-bucket.yaml": {
        "read": {"s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject"},
        "readwrite": {"s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"},
    },
    "platform-database.yaml": {"connect": {"rds-db:connect"}},
}
# The only Resource each policy may reference: its own resource's ARN (or name).
OWN_RESOURCE = {
    "platform-queue.yaml": ["queue.status.ackResourceMetadata.arn"],
    "platform-table.yaml": ["table.status.ackResourceMetadata.arn"],
    "platform-topic.yaml": ["topic.status.ackResourceMetadata.arn"],
    "platform-bucket.yaml": ["bucket.spec.name"],
    "platform-database.yaml": ["db.status.dbiResourceID"],
}


def policy_expression(rgd_file: str) -> str:
    rgd = yaml.safe_load((RGDS / rgd_file).read_text())
    [policy] = [r for r in rgd["spec"]["resources"] if r["template"]["kind"] == "Policy"]
    return policy["template"]["spec"]["policyDocument"]


def actions_by_access(expr: str, levels: list[str]) -> dict[str, set[str]]:
    """Map access level -> action list from the CEL ternary chain in policyDocument."""
    lists = [set(json.loads(m)) for m in re.findall(r"'(\[\"[^']*\"\])'", expr)]
    branches = re.findall(r'schema\.spec\.access == "(\w+)"', expr)
    if not branches:  # single access level: actions are literal (see static_actions)
        assert not lists and len(levels) == 1, expr
        return {levels[0]: set()}
    # cond1 ? L1 : cond2 ? L2 : L3  -> branches name all but the last level
    remaining = [lvl for lvl in levels if lvl not in branches]
    assert len(remaining) == 1, (branches, levels)
    return dict(zip([*branches, remaining[0]], lists, strict=True))


def static_actions(expr: str) -> set[str]:
    """Actions that are literal in the document (outside the per-access ternary)."""
    return {
        a
        for chunk in re.findall(r'\\?"Action\\?":\[([^\]]*)\]', expr)
        for a in re.findall(r'"([a-z0-9-]+:\w+)"', chunk)
    }


def boundary_actions() -> set[str]:
    tf = BOUNDARY_TF.read_text()
    block = tf[tf.index('sid    = "DataPlaneOnly"') : tf.index('sid       = "NeverControlPlane"')]
    return set(re.findall(r'"([a-z0-9-]+:[\w*]+)"', block))


def allowed_by_boundary(action: str, boundary: set[str]) -> bool:
    service = action.split(":")[0]
    return action in boundary or f"{service}:*" in boundary


@pytest.mark.parametrize("rgd_file", sorted(EXPECTED))
def test_access_levels_grant_exactly_the_documented_actions(rgd_file):
    expr = policy_expression(rgd_file)
    levels = list(EXPECTED[rgd_file])
    got = actions_by_access(expr, levels)
    fixed = static_actions(expr)
    for level, expected in EXPECTED[rgd_file].items():
        assert got[level] | fixed == expected, f"{rgd_file} access={level}"


@pytest.mark.parametrize("rgd_file", sorted(EXPECTED))
def test_policy_resources_are_only_the_rgds_own_resource(rgd_file):
    expr = policy_expression(rgd_file)
    assert '"Resource":"*"' not in expr.replace(" ", "") and "'*'" not in expr
    refs = set(re.findall(r"\b(\w+)\.(?:status|spec)\.[\w.]+", expr)) - {"schema"}
    allowed_ids = {ref.split(".")[0] for ref in OWN_RESOURCE[rgd_file]}
    assert refs == allowed_ids, f"{rgd_file} policy references {refs}, expected only {allowed_ids}"
    for ref in OWN_RESOURCE[rgd_file]:
        assert ref in expr


@pytest.mark.parametrize("rgd_file", sorted(EXPECTED))
def test_every_action_is_within_the_permissions_boundary(rgd_file):
    boundary = boundary_actions()
    expr = policy_expression(rgd_file)
    actions = set().union(*actions_by_access(expr, list(EXPECTED[rgd_file])).values(), static_actions(expr))
    outside = {a for a in actions if not allowed_by_boundary(a, boundary)}
    assert not outside, f"{rgd_file} grants actions outside the boundary: {outside}"


def test_role_trust_is_pinned_to_one_service_account():
    rgd = yaml.safe_load((RGDS / "platform-workload-identity.yaml").read_text())
    [role] = rgd["spec"]["resources"]
    trust = role["template"]["spec"]["assumeRolePolicyDocument"]
    assert "sts:AssumeRoleWithWebIdentity" in trust
    assert "system:serviceaccount:' + schema.spec.namespace + ':' + schema.spec.serviceAccount" in trust
    assert ':aud":"sts.amazonaws.com' in trust
    assert "permissionsBoundary" in role["template"]["spec"]
