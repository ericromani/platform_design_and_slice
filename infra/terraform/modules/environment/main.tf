# One complete environment: VPC -> EKS (+IRSA) -> platform IAM. This is the prerequisite
# every microservice deploy depends on; developers never edit it.
locals {
  tags = {
    environment = var.environment
    managed-by  = "terraform"
    owner       = "platform"
  }
}

module "vpc" {
  source       = "../vpc"
  name         = var.environment
  cidr         = var.vpc_cidr
  azs          = var.azs
  cluster_name = var.environment
  tags         = local.tags
}

# GitHub Actions OIDC, so the central deploy workflow needs no static AWS keys.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  tags           = local.tags
}

module "eks" {
  source               = "../eks"
  name                 = var.environment
  vpc_id               = module.vpc.vpc_id
  private_subnet_ids   = module.vpc.private_subnet_ids
  node_instance_types  = var.node_instance_types
  node_min             = var.node_min
  node_max             = var.node_max
  admin_principal_arns = concat(var.platform_admin_arns, ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/platform-deploy-${var.environment}"])
  tags                 = local.tags
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

module "platform_iam" {
  source                   = "../platform-iam"
  environment              = var.environment
  oidc_provider_arn        = module.eks.oidc_provider_arn
  oidc_issuer              = module.eks.oidc_issuer
  github_oidc_provider_arn = aws_iam_openid_connect_provider.github.arn
  github_org               = var.github_org
  # staging: deploy + promote's verify job + decommission; prod: promote + decommission.
  deploy_workflows = var.environment == "prod" ? ["promote.yaml", "decommission.yaml"] : ["deploy.yaml", "promote.yaml", "decommission.yaml"]
  tags             = local.tags
}

# Cluster facts the deploy pipeline injects as the chart's `global` values.
resource "aws_ssm_parameter" "globals" {
  name = "/platform/${var.environment}/chart-globals"
  type = "String"
  value = jsonencode({
    environment            = var.environment
    accountId              = data.aws_caller_identity.current.account_id
    region                 = data.aws_region.current.region
    clusterName            = module.eks.cluster_name
    oidcProviderArn        = module.eks.oidc_provider_arn
    oidcIssuer             = module.eks.oidc_issuer
    vpcId                  = module.vpc.vpc_id
    dbSubnetGroupName      = module.vpc.db_subnet_group_name
    nodeSecurityGroupId    = module.eks.node_security_group_id
    permissionsBoundaryArn = module.platform_iam.workload_boundary_arn
  })
  tags = local.tags
}
