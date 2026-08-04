variable "name_prefix" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type = string
}

variable "cluster_arn" {
  type = string
}

variable "execution_role_arn" {
  description = "ECS task execution role ARN (modules/ecs) -- the scheduler's own IAM role needs iam:PassRole on it to launch a task."
  type        = string
}

variable "task_jobs_role_arn" {
  description = "ECS task role ARN used by both scheduled jobs (modules/ecs) -- same iam:PassRole requirement."
  type        = string
}

variable "verify_audit_chain_task_definition_arn" {
  type = string
}

variable "retry_calendar_sync_task_definition_arn" {
  type = string
}

variable "verify_schedule_expression" {
  description = "design.md §4.3: \"dispara el job por cron (p.ej. cada hora)\"."
  type        = string
  default     = "rate(1 hour)"
}

variable "retry_schedule_expression" {
  description = "design.md §7.5: bounded retry/reconciliation job cadence."
  type        = string
  default     = "rate(15 minutes)"
}

variable "metric_namespace" {
  description = "Custom CloudWatch metric namespace for AuditChainTamper/AuditChainVerifyHeartbeat -- NOT named explicitly anywhere in design.md §4.3, chosen here and documented as a contract the future verify-audit-chain job's own metric-publish call MUST match exactly."
  type        = string
  default     = "Kureha/Audit"
}

variable "heartbeat_alarm_period_seconds" {
  description = "design.md §4.3: dead-man's switch window is \"~2x el intervalo\" of the verify job's own schedule -- default here is 2x the default hourly schedule (7200s). Must be recalculated if verify_schedule_expression changes."
  type        = number
  default     = 7200
}

variable "alarm_email" {
  description = "Optional email address subscribed to the SNS alert topic (design.md §4.3: \"canal on-call email/Slack/PagerDuty\"). Leave null to wire the topic without a subscriber and add one out-of-band (e.g. a PagerDuty integration) -- avoids hardcoding a real on-call address into version control."
  type        = string
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}
