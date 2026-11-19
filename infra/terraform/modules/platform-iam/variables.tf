variable "environment" {
  description = "staging | prod"
  type        = string
}

variable "oidc_provider_arn" {
  description = "IAM OIDC provider of the environment's cluster (IRSA)."
  type        = string
}

variable "oidc_issuer" {
  description = "Cluster OIDC issuer without scheme (e.g. oidc.eks.us-east-1.amazonaws.com/id/ABC)."
  type        = string
}

variable "ack_namespace" {
  description = "Namespace the ACK controllers run in."
  type        = string
  default     = "ack-system"
}

variable "ack_services" {
  description = "ACK controllers that get an IRSA role."
  type        = list(string)
  default     = ["iam", "sqs", "sns", "s3", "dynamodb", "rds", "ec2"]
}

variable "github_oidc_provider_arn" {
  description = "IAM OIDC provider for token.actions.githubusercontent.com. Empty disables the deploy role."
  type        = string
  default     = ""
}

variable "github_org" {
  description = "GitHub org whose repos may assume the deploy role (only from the matching GitHub environment)."
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
