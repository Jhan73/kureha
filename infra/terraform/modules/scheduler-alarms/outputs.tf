output "sns_topic_arn" {
  value = aws_sns_topic.audit_alerts.arn
}

output "scheduler_role_arn" {
  value = aws_iam_role.scheduler.arn
}

output "verify_audit_chain_schedule_arn" {
  value = aws_scheduler_schedule.verify_audit_chain.arn
}

output "retry_calendar_sync_schedule_arn" {
  value = aws_scheduler_schedule.retry_calendar_sync.arn
}

output "audit_chain_tamper_alarm_arn" {
  value = aws_cloudwatch_metric_alarm.audit_chain_tamper.arn
}

output "audit_chain_verify_heartbeat_alarm_arn" {
  value = aws_cloudwatch_metric_alarm.audit_chain_verify_heartbeat.arn
}
