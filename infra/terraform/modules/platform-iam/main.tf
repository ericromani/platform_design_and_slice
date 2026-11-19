# Account-level IAM the platform needs in each environment:
#   1. A permissions boundary capping every service (workload) role.
#   2. IRSA roles for the ACK controllers. The IAM controller can only create roles that
#      carry the boundary, so the platform can never mint a role more powerful than it.
#   3. (optional) The GitHub Actions deploy role used by the central deploy workflow.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account = data.aws_caller_identity.current.account_id
  region  = data.aws_region.current.region
}

# ---- 1. workload permissions boundary ----------------------------------------------------
data "aws_iam_policy_document" "workload_boundary" {
  statement {
    sid    = "DataPlaneOnly"
    effect = "Allow"
    actions = [
      "sqs:*", "sns:Publish", "sns:GetTopicAttributes",
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation",
      "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan",
      "dynamodb:DescribeTable", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem", "rds-db:connect",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "NeverControlPlane"
    effect    = "Deny"
    actions   = ["iam:*", "organizations:*", "account:*", "sts:AssumeRole"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "workload_boundary" {
  name        = "platform-workload-boundary"
  description = "Maximum permissions any service role created by the platform may have (${var.environment})"
  policy      = data.aws_iam_policy_document.workload_boundary.json
  tags        = var.tags
}

# ---- 2. ACK controller IRSA roles --------------------------------------------------------
data "aws_iam_policy_document" "ack_trust" {
  for_each = toset(var.ack_services)
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_issuer}:sub"
      values   = ["system:serviceaccount:${var.ack_namespace}:ack-${each.key}-controller"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ack" {
  for_each             = toset(var.ack_services)
  name                 = "ack-${each.key}-controller"
  assume_role_policy   = data.aws_iam_policy_document.ack_trust[each.key].json
  max_session_duration = 3600
  tags                 = var.tags
}

locals {
  # Per-controller permissions, scoped to the account/region. Each controller manages
  # exactly one AWS service.
  ack_actions = {
    sqs      = ["sqs:*"]
    sns      = ["sns:*"]
    s3       = ["s3:*"]
    dynamodb = ["dynamodb:*"]
    rds      = ["rds:*", "secretsmanager:CreateSecret", "secretsmanager:TagResource", "kms:DescribeKey"]
    ec2      = ["ec2:*SecurityGroup*", "ec2:Describe*", "ec2:CreateTags", "ec2:DeleteTags"]
  }
}

resource "aws_iam_role_policy" "ack_service" {
  for_each = { for k, v in local.ack_actions : k => v if contains(var.ack_services, k) }
  name     = "ack-${each.key}"
  role     = aws_iam_role.ack[each.key].id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = each.value, Resource = "*" }]
  })
}

# The IAM controller: may create/update roles ONLY with the workload boundary attached,
# may never remove or replace a boundary, and may not touch platform-owned roles.
data "aws_iam_policy_document" "ack_iam" {
  statement {
    sid       = "CreateBoundedRolesOnly"
    actions   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
    resources = ["arn:aws:iam::${local.account}:role/*-${var.environment}"]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.workload_boundary.arn]
    }
  }
  statement {
    sid = "ManageServiceRoles"
    actions = [
      "iam:GetRole", "iam:UpdateRole", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:ListRoleTags",
    ]
    resources = ["arn:aws:iam::${local.account}:role/*-${var.environment}"]
  }
  statement {
    sid = "ManageServicePolicies"
    actions = [
      "iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion",
      "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions", "iam:TagPolicy",
      "iam:UntagPolicy", "iam:ListPolicyTags",
    ]
    resources = ["arn:aws:iam::${local.account}:policy/*"]
  }
  statement {
    sid       = "NeverRemoveBoundary"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }
  statement {
    sid       = "NeverTouchPlatformIam"
    effect    = "Deny"
    actions   = ["iam:*"]
    resources = [aws_iam_policy.workload_boundary.arn, "arn:aws:iam::${local.account}:role/ack-*", "arn:aws:iam::${local.account}:role/platform-*"]
  }
}

resource "aws_iam_role_policy" "ack_iam" {
  count  = contains(var.ack_services, "iam") ? 1 : 0
  name   = "ack-iam-bounded"
  role   = aws_iam_role.ack["iam"].id
  policy = data.aws_iam_policy_document.ack_iam.json
}

# ---- 3. GitHub Actions deploy role -------------------------------------------------------
# Assumed by the central deploy workflow (platform/workflows) only from a job running in
# the GitHub environment matching this AWS environment. It can reach the cluster API and
# the promotion ledger; it cannot create AWS resources (ACK does that, from Git).
data "aws_iam_policy_document" "deploy_trust" {
  count = var.github_oidc_provider_arn == "" ? 0 : 1
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/*:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  count              = var.github_oidc_provider_arn == "" ? 0 : 1
  name               = "platform-deploy-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.deploy_trust[0].json
  tags               = var.tags
}

resource "aws_iam_role_policy" "deploy" {
  count = var.github_oidc_provider_arn == "" ? 0 : 1
  name  = "platform-deploy"
  role  = aws_iam_role.deploy[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Cluster", Effect = "Allow", Action = ["eks:DescribeCluster"], Resource = "*" },
      {
        Sid      = "PromotionLedger"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:PutParameter", "ssm:GetParametersByPath", "ssm:DeleteParameter"]
        Resource = "arn:aws:ssm:${local.region}:${local.account}:parameter/platform/promotions/*"
      },
    ]
  })
}
