variable "environment" {
  description = "staging | prod"
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be staging or prod"
  }
}

variable "vpc_cidr" {
  type = string
}

variable "azs" {
  type = list(string)
}

variable "node_instance_types" {
  type    = list(string)
  default = ["m7i.large"]
}

variable "node_min" {
  type    = number
  default = 2
}

variable "node_max" {
  type    = number
  default = 6
}

variable "platform_admin_arns" {
  description = "Platform team SSO role ARNs granted cluster-admin."
  type        = list(string)
  default     = []
}

variable "github_org" {
  type = string
}
