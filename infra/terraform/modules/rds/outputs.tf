output "db_instance_id" {
  value = aws_db_instance.this.id
}

output "db_address" {
  value = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "db_name" {
  value = var.db_name
}

output "master_username" {
  value = var.master_username
}

output "database_url_secret_arn" {
  value = aws_secretsmanager_secret.database_url.arn
}

output "runtime_database_url_secret_arn" {
  value = aws_secretsmanager_secret.runtime_database_url.arn
}

output "app_runtime_password_secret_arn" {
  value = aws_secretsmanager_secret.app_runtime_password.arn
}

output "master_password_secret_arn" {
  value = aws_secretsmanager_secret.master_password.arn
}
