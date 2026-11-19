# One local environment in its own LocalStack account. Mirrors modules/environment, with
# kind standing in for EKS: the OIDC provider points at the kind cluster's issuer, and
# NAT/RDS pieces LocalStack Community lacks are switched off.
terraform {
  required_providers {
    aws   = { source = "hashicorp/aws" }
    local = { source = "hashicorp/local" }
  }
}

variable "environment" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "kind_issuer" {
  description = "service-account-issuer of the kind cluster (kind default)."
  type        = string
  default     = "https://kubernetes.default.svc.cluster.local"
}

variable "globals_file" {
  type = string
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  tags = { environment = var.environment, managed-by = "terraform", owner = "platform" }
}

module "vpc" {
  source                 = "../../../modules/vpc"
  name                   = var.environment
  cidr                   = var.vpc_cidr
  azs                    = ["us-east-1a", "us-east-1b"]
  cluster_name           = "platform-local"
  enable_nat_gateway     = false
  create_db_subnet_group = false
  tags                   = local.tags
}

# The EKS module would create this from the real cluster issuer.
resource "aws_iam_openid_connect_provider" "kind" {
  url             = var.kind_issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["0000000000000000000000000000000000000000"]
  tags            = local.tags
}

module "platform_iam" {
  source            = "../../../modules/platform-iam"
  environment       = var.environment
  oidc_provider_arn = aws_iam_openid_connect_provider.kind.arn
  oidc_issuer       = replace(var.kind_issuer, "https://", "")
  ack_namespace     = "ack-${var.environment}"
  ack_services      = ["iam", "sqs", "sns", "s3", "dynamodb"]
  tags              = local.tags
}

locals {
  globals = {
    environment            = var.environment
    accountId              = data.aws_caller_identity.current.account_id
    region                 = data.aws_region.current.region
    clusterName            = "platform-local"
    oidcProviderArn        = aws_iam_openid_connect_provider.kind.arn
    oidcIssuer             = replace(var.kind_issuer, "https://", "")
    vpcId                  = module.vpc.vpc_id
    permissionsBoundaryArn = module.platform_iam.workload_boundary_arn
    local                  = true
    awsEndpointUrl         = "http://localstack:4566"
    awsS3EndpointUrl       = "http://s3.localstack:4566"
  }
}

resource "aws_ssm_parameter" "globals" {
  name  = "/platform/${var.environment}/chart-globals"
  type  = "String"
  value = jsonencode(local.globals)
  tags  = local.tags
}

# The deploy scripts read this file locally (in CI they read the SSM parameter).
resource "local_file" "globals" {
  filename        = var.globals_file
  content         = yamlencode({ global = local.globals })
  file_permission = "0644"
}

output "globals" {
  value = local.globals
}
