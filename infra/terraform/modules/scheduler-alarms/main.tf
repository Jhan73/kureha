# EventBridge Scheduler + ECS scheduled tasks + CloudWatch alarms/SNS
# (design.md §4.3/§7.5/§20.1, ADR-19): "el verificador se murio" also
# alerts -- dead-man's switch via `treatMissingData=breaching`, distinct
# from the tamper alarm itself.
#
# **Per-tenant dimensioning, flagged simplification:** design.md §4.3 says
# the tamper/heartbeat metrics carry a `tenant_id` dimension, so a fully
# faithful implementation would alarm PER TENANT. Tenants are created at
# runtime by the application (no static, IaC-known tenant list) -- static
# Terraform cannot enumerate an unbounded, runtime-created dimension value
# set to generate one `aws_cloudwatch_metric_alarm` per tenant. This module
# defines ONE aggregate alarm per metric instead (no dimension filter,
# across all tenants combined) -- catches "some tenant's chain is tampered"
# / "the job stopped running for everyone", but not "which tenant" without
# checking the metric's own per-tenant datapoints after the alarm fires.
# A future iteration could drive per-tenant alarms from a Lambda/custom
# resource reading the `tenants` table, out of this task's scope.

resource "aws_sns_topic" "audit_alerts" {
  name = "${var.name_prefix}-audit-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "audit_alerts_email" {
  count     = var.alarm_email == null ? 0 : 1
  topic_arn = aws_sns_topic.audit_alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# --- EventBridge Scheduler IAM role ---

data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scheduler_run_task" {
  statement {
    sid     = "RunEcsTask"
    actions = ["ecs:RunTask"]
    resources = [
      var.verify_audit_chain_task_definition_arn,
      var.retry_calendar_sync_task_definition_arn,
    ]

    condition {
      test     = "ArnLike"
      variable = "ecs:cluster"
      values   = [var.cluster_arn]
    }
  }

  statement {
    sid       = "PassEcsRoles"
    actions   = ["iam:PassRole"]
    resources = [var.execution_role_arn, var.task_jobs_role_arn]
  }
}

resource "aws_iam_role_policy" "scheduler_run_task" {
  name   = "${var.name_prefix}-scheduler-run-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_run_task.json
}

# --- Schedules ---

resource "aws_scheduler_schedule" "verify_audit_chain" {
  name       = "${var.name_prefix}-verify-audit-chain"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.verify_schedule_expression

  target {
    arn      = var.cluster_arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = var.verify_audit_chain_task_definition_arn
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = var.private_subnet_ids
        security_groups  = [var.ecs_security_group_id]
        assign_public_ip = false
      }
    }
  }
}

resource "aws_scheduler_schedule" "retry_calendar_sync" {
  name       = "${var.name_prefix}-retry-calendar-sync"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.retry_schedule_expression

  target {
    arn      = var.cluster_arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = var.retry_calendar_sync_task_definition_arn
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = var.private_subnet_ids
        security_groups  = [var.ecs_security_group_id]
        assign_public_ip = false
      }
    }
  }
}

# --- CloudWatch alarms (design.md §4.3, ADR-19) ---

resource "aws_cloudwatch_metric_alarm" "audit_chain_tamper" {
  alarm_name          = "${var.name_prefix}-AuditChainTamper"
  alarm_description   = "Fires when the hash-chain verify job recomputes a row_hash that does not match the stored value, or finds a gap in seq (design.md §4.3). Missing data is NOT breaching here -- no datapoint just means no tamper was reported this period; see the separate heartbeat alarm for \"the job stopped running\"."
  namespace           = var.metric_namespace
  metric_name         = "AuditChainTamper"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.audit_alerts.arn]
  ok_actions    = [aws_sns_topic.audit_alerts.arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "audit_chain_verify_heartbeat" {
  alarm_name          = "${var.name_prefix}-AuditChainVerifyHeartbeat"
  alarm_description   = "Dead-man's switch (design.md §4.3, ADR-19): fires if the verify job does not emit a heartbeat within ~2x its own schedule interval -- treat_missing_data=breaching is the point, \"the verifier died\" must alert too, not fail silently."
  namespace           = var.metric_namespace
  metric_name         = "AuditChainVerifyHeartbeat"
  statistic           = "Sum"
  period              = var.heartbeat_alarm_period_seconds
  evaluation_periods  = 1
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.audit_alerts.arn]
  ok_actions    = [aws_sns_topic.audit_alerts.arn]

  tags = var.tags
}
