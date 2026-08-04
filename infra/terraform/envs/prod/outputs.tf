output "alb_dns_name" {
  value = module.alb_waf.alb_dns_name
}

output "cloudfront_domain_name" {
  value = module.frontend_cdn.cloudfront_domain_name
}

output "spa_bucket_name" {
  value = module.frontend_cdn.bucket_name
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "rds_address" {
  value = module.rds.db_address
}

output "sns_audit_alerts_topic_arn" {
  value = module.scheduler_alarms.sns_topic_arn
}

output "bootstrap_db_task_definition_arn" {
  description = "Run this ONCE via `aws ecs run-task` before the first migrate task (see README.md's runbook)."
  value       = module.ecs.bootstrap_db_task_definition_arn
}

output "migrate_task_definition_arn" {
  description = "Run this via `aws ecs run-task` on every deploy, after bootstrap_db_task_definition_arn has run at least once."
  value       = module.ecs.migrate_task_definition_arn
}
