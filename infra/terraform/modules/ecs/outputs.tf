output "cluster_arn" {
  value = aws_ecs_cluster.this.arn
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.api.name
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "task_jobs_role_arn" {
  value = aws_iam_role.task_jobs.arn
}

output "verify_audit_chain_task_definition_arn" {
  value = aws_ecs_task_definition.verify_audit_chain.arn
}

output "retry_calendar_sync_task_definition_arn" {
  value = aws_ecs_task_definition.retry_calendar_sync.arn
}

output "bootstrap_db_task_definition_arn" {
  value = aws_ecs_task_definition.bootstrap_db.arn
}

output "migrate_task_definition_arn" {
  value = aws_ecs_task_definition.migrate.arn
}
