variable "name" {
  description = "Cluster name (one cluster per environment)."
  type        = string
}

variable "kubernetes_version" {
  type    = string
  default = "1.34"
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  description = "Nodes and the control plane ENIs live in private subnets."
  type        = list(string)
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

variable "admin_principal_arns" {
  description = "IAM principals granted cluster-admin through EKS access entries (platform team, deploy role)."
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
