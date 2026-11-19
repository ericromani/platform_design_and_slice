output "chart_globals_parameter" {
  description = "SSM parameter holding the chart `global` values for this environment."
  value       = aws_ssm_parameter.globals.name
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "deploy_role_arn" {
  value = module.platform_iam.deploy_role_arn
}

output "ack_role_arns" {
  value = module.platform_iam.ack_role_arns
}
