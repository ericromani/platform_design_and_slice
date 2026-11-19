output "vpc_id" {
  value = aws_vpc.this.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "db_subnet_group_name" {
  value = var.create_db_subnet_group ? aws_db_subnet_group.this[0].name : ""
}
