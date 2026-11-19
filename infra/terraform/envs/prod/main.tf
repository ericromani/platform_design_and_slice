# Production: only image digests verified in staging can be deployed here (the promote
# workflow checks the staging verification record before it touches this cluster).
terraform {
  required_version = ">= 1.6"
  backend "s3" {
    bucket       = "example-platform-tfstate-prod"
    key          = "platform/prod.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["222222222222"]
}

module "environment" {
  source      = "../../modules/environment"
  environment = "prod"
  vpc_cidr    = "10.20.0.0/16"
  azs         = ["us-east-1a", "us-east-1b", "us-east-1c"]
  node_min    = 3
  node_max    = 12
  github_org  = "example-org"
}

output "environment" {
  value = module.environment
}
