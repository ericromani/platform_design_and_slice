output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.this.arn
}

output "oidc_issuer" {
  description = "Issuer without scheme, as IRSA trust-policy condition keys expect."
  value       = replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")
}

output "node_security_group_id" {
  description = "Cluster security group (attached to managed nodes); RDS security groups admit it."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}
