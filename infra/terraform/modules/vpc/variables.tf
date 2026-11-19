variable "name" {
  description = "Environment name (staging | prod); prefixes every resource."
  type        = string
}

variable "cidr" {
  description = "VPC CIDR block."
  type        = string
}

variable "azs" {
  description = "Availability zones to spread subnets across (2-3)."
  type        = list(string)
}

variable "enable_nat_gateway" {
  description = "Create one NAT gateway per AZ for private subnet egress. Disable for LocalStack."
  type        = bool
  default     = true
}

variable "cluster_name" {
  description = "EKS cluster name, used for the subnet discovery tags the AWS Load Balancer Controller needs."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

variable "create_db_subnet_group" {
  description = "Create the RDS DB subnet group used by the chart's aws.rds option. Disable where RDS is unavailable (LocalStack Community)."
  type        = bool
  default     = true
}
