# Staging: pre-production. Every release lands here first (enforced by the promote
# workflow, which requires a staging verification record for the exact image digest).
terraform {
  required_version = ">= 1.6"
  backend "s3" {
    bucket       = "example-platform-tfstate-staging"
    key          = "platform/staging.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["111111111111"]
}

module "environment" {
  source      = "../../modules/environment"
  environment = "staging"
  vpc_cidr    = "10.10.0.0/16"
  azs         = ["us-east-1a", "us-east-1b", "us-east-1c"]
  node_min    = 2
  node_max    = 4
  github_org  = "example-org"
}

output "environment" {
  value = module.environment
}
