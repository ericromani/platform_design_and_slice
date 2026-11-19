output "workload_boundary_arn" {
  value = aws_iam_policy.workload_boundary.arn
}

output "ack_role_arns" {
  value = { for k, r in aws_iam_role.ack : k => r.arn }
}

output "deploy_role_arn" {
  value = try(aws_iam_role.deploy[0].arn, "")
}
