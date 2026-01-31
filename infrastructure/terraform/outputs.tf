# OpenRadiomics - Terraform Outputs

output "rds_endpoint" {
  description = "RDS instance endpoint (hostname)"
  value       = aws_db_instance.postgres.endpoint
}

output "rds_address" {
  description = "RDS instance hostname (without port)"
  value       = aws_db_instance.postgres.address
}

output "rds_port" {
  description = "RDS instance port"
  value       = aws_db_instance.postgres.port
}

output "database_name" {
  description = "Name of the database"
  value       = aws_db_instance.postgres.db_name
}

output "database_username" {
  description = "Master username for the database"
  value       = aws_db_instance.postgres.username
}

output "connection_string" {
  description = "PostgreSQL connection string format (password not included)"
  value       = "postgresql://${aws_db_instance.postgres.username}:<PASSWORD>@${aws_db_instance.postgres.endpoint}/${aws_db_instance.postgres.db_name}"
}

output "psql_command" {
  description = "Command to connect via psql"
  value       = "psql -h ${aws_db_instance.postgres.address} -p ${aws_db_instance.postgres.port} -U ${aws_db_instance.postgres.username} -d ${aws_db_instance.postgres.db_name}"
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "security_group_id" {
  description = "RDS security group ID"
  value       = aws_security_group.rds.id
}

output "subnet_ids" {
  description = "Subnet IDs used by RDS"
  value       = [aws_subnet.public_a.id, aws_subnet.public_b.id]
}

output "rds_instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.postgres.identifier
}

output "aws_account_id" {
  description = "AWS account ID"
  value       = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  description = "AWS region"
  value       = data.aws_region.current.name
}
