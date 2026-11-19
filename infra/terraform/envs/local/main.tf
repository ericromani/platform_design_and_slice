# Local prerequisite: the "central infra" for both environments, applied to LocalStack.
# Each environment is a separate LocalStack account (LocalStack derives the account from
# a 12-digit access key ID), exactly as staging and prod are separate AWS accounts.
#
#   terraform -chdir=infra/terraform/envs/local init && terraform -chdir=... apply
#   (or: make infra)
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws   = { source = "hashicorp/aws", version = "~> 6.0" }
    local = { source = "hashicorp/local", version = "~> 2.5" }
  }
}

locals {
  endpoint = "http://localhost:4566"
}

provider "aws" {
  alias                       = "staging"
  region                      = "us-east-1"
  access_key                  = "111111111111"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = false
  endpoints {
    ec2 = local.endpoint
    iam = local.endpoint
    sts = local.endpoint
    ssm = local.endpoint
  }
}

provider "aws" {
  alias                       = "prod"
  region                      = "us-east-1"
  access_key                  = "222222222222"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = false
  endpoints {
    ec2 = local.endpoint
    iam = local.endpoint
    sts = local.endpoint
    ssm = local.endpoint
  }
}

module "staging" {
  source       = "./environment"
  providers    = { aws = aws.staging }
  environment  = "staging"
  vpc_cidr     = "10.10.0.0/16"
  globals_file = "${path.root}/../../../../local/generated/staging-globals.yaml"
}

module "prod" {
  source       = "./environment"
  providers    = { aws = aws.prod }
  environment  = "prod"
  vpc_cidr     = "10.20.0.0/16"
  globals_file = "${path.root}/../../../../local/generated/prod-globals.yaml"
}

output "staging" {
  value = module.staging.globals
}

output "prod" {
  value = module.prod.globals
}
