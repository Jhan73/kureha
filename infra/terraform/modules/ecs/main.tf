# ECS Fargate (design.md §20.1/§20.2, ADR-20): "API+agente, misma imagen;
# jobs = scheduled Fargate tasks via EventBridge". One cluster, one image,
# multiple task definitions (the long-running API service + several one-off
# / scheduled maintenance tasks).

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-cluster" })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/kureha/api/${var.environment_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "jobs" {
  name              = "/kureha/jobs/${var.environment_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# --- IAM ---
#
# design.md §20.3: "task execution role (pull de imagen, logs) separado del
# task role (Secrets Manager, SNS, CloudWatch, EventBridge)". **Deliberate,
# flagged deviation from that table's literal wording:** AWS's own ECS
# platform requires the EXECUTION role (not the task role) to hold
# `secretsmanager:GetSecretValue`/`kms:Decrypt` for any secret referenced by
# a task definition's `secrets` block (env-var injection resolved at
# container launch, before the task role is ever assumed) -- this is a hard
# AWS platform constraint, not a design choice made here. The TASK role
# below is reserved for what the APPLICATION ITSELF calls via boto3 at
# runtime (`AesGcmVault`'s KEK fetch, the verify/retry jobs' custom
# CloudWatch metrics) -- matching the spirit of design.md's split even
# though the execution role necessarily carries one more permission than
# its own prose literally states.

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    sid     = "ReadInjectedSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      var.database_url_secret_arn,
      var.runtime_database_url_secret_arn,
      var.master_password_secret_arn,
      var.app_runtime_password_secret_arn,
      var.identity_access_token_secret_arn,
      var.calendar_oauth_state_secret_arn,
      var.google_oauth_secret_arn,
      var.supabase_secret_arn,
      var.anthropic_api_key_secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "${var.name_prefix}-ecs-execution-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task_api" {
  name               = "${var.name_prefix}-ecs-task-api"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "task_api" {
  # AesGcmVault fetches the KEK itself at runtime (design.md ADR-12, §22.6)
  statement {
    sid       = "ReadKek"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.kek_secret_arn]
  }
}

resource "aws_iam_role_policy" "task_api" {
  name   = "${var.name_prefix}-ecs-task-api"
  role   = aws_iam_role.task_api.id
  policy = data.aws_iam_policy_document.task_api.json
}

resource "aws_iam_role" "task_jobs" {
  name               = "${var.name_prefix}-ecs-task-jobs"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "task_jobs" {
  # verify-audit-chain publishes AuditChainTamper/AuditChainVerifyHeartbeat
  # (design.md §4.3, ADR-19); retry-calendar-sync's SyncAppointmentToCalendar
  # path goes through AesGcmVault too, same KEK read as the API.
  statement {
    sid       = "PublishHashChainMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # PutMetricData does not support resource-level scoping
  }

  statement {
    sid       = "ReadKek"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.kek_secret_arn]
  }
}

resource "aws_iam_role_policy" "task_jobs" {
  name   = "${var.name_prefix}-ecs-task-jobs"
  role   = aws_iam_role.task_jobs.id
  policy = data.aws_iam_policy_document.task_jobs.json
}

# --- API service task definition ---

locals {
  api_environment = [
    for k, v in merge({
      ENVIRONMENT          = var.environment_name
      AWS_DEFAULT_REGION   = var.aws_default_region
      CORS_ALLOWED_ORIGINS = var.cors_allowed_origins
      # AWS_ENDPOINT_URL deliberately NOT set -- boto3 falls back to real
      # AWS when absent (design.md §22.4/§22.6), the single env-var switch
      # between LocalStack and production.
    }, var.extra_environment) : { name = k, value = v }
  ]

  api_secrets = [
    { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
    { name = "RUNTIME_DATABASE_URL", valueFrom = var.runtime_database_url_secret_arn },
    { name = "IDENTITY_ACCESS_TOKEN_SECRET", valueFrom = var.identity_access_token_secret_arn },
    { name = "CALENDAR_OAUTH_STATE_SECRET", valueFrom = var.calendar_oauth_state_secret_arn },
    { name = "CALENDAR_GOOGLE_CLIENT_ID", valueFrom = "${var.google_oauth_secret_arn}:client_id::" },
    { name = "CALENDAR_GOOGLE_CLIENT_SECRET", valueFrom = "${var.google_oauth_secret_arn}:client_secret::" },
    { name = "SUPABASE_URL", valueFrom = "${var.supabase_secret_arn}:url::" },
    { name = "SUPABASE_ANON_KEY", valueFrom = "${var.supabase_secret_arn}:anon_key::" },
    { name = "ANTHROPIC_API_KEY", valueFrom = var.anthropic_api_key_secret_arn },
  ]

  jobs_log_options = {
    "awslogs-group"         = aws_cloudwatch_log_group.jobs.name
    "awslogs-region"        = var.aws_region
    "awslogs-stream-prefix" = "jobs"
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task_api.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.image_uri
      essential = true

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      environment = local.api_environment
      secrets     = local.api_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "api" {
  name            = "${var.name_prefix}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [var.ecs_security_group_id]
    # No public IP -- API tasks live in private subnets, reachable only via
    # the ALB (design.md §20.1/§20.2).
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "api"
    container_port   = var.container_port
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = var.tags
}

# --- One-off maintenance task definitions ---
#
# `Database not publicly reachable` (design.md §20) means Terraform itself
# -- typically run from CI/a laptop OUTSIDE the VPC -- CANNOT reach RDS
# directly to bootstrap it or run migrations; these MUST run as one-off
# Fargate tasks inside the private subnets instead. Both are `aws_ecs_
# task_definition` only (no `aws_ecs_service`) -- invoked on demand via
# `aws ecs run-task` (see infra/terraform/README.md's runbook), not
# automatically triggered by `terraform apply`.

resource "aws_ecs_task_definition" "bootstrap_db" {
  family                   = "${var.name_prefix}-bootstrap-db"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task_jobs.arn

  container_definitions = jsonencode([
    {
      name = "bootstrap-db"
      # Uses the plain postgres:16 image (has `psql`, matches
      # docker-compose.yml's own local Postgres image) rather than the
      # backend image -- this step is pure DDL/role bootstrap, not
      # application code, and running it against the backend image would
      # need psql installed there for no other reason.
      image     = "postgres:16"
      essential = true
      command   = ["sh", "-c", local.bootstrap_sql_script]

      environment = [
        { name = "PGHOST", value = var.db_host },
        { name = "PGPORT", value = tostring(var.db_port) },
        { name = "PGDATABASE", value = var.db_name },
        { name = "PGUSER", value = var.db_master_username },
      ]

      secrets = [
        { name = "PGPASSWORD", valueFrom = var.master_password_secret_arn },
        { name = "APP_RUNTIME_PASSWORD", valueFrom = var.app_runtime_password_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options   = local.jobs_log_options
      }
    }
  ])

  tags = var.tags
}

locals {
  # tasks.md 16.1: "CREATE EXTENSION IF NOT EXISTS pgcrypto" /
  # "CREATE EXTENSION IF NOT EXISTS btree_gist" as the RDS master user
  # before the first `alembic upgrade head` -- mirrors
  # infra/postgres/init/01_extensions.sql. The app_runtime role creation
  # mirrors infra/postgres/init/02_app_runtime_role.sql, whose own comment
  # explicitly deferred this step to Phase 16's RDS bootstrap ("the role
  # creation belongs next to it").
  bootstrap_sql_script = <<-EOT
    set -eu
    psql -v ON_ERROR_STOP=1 \
      -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;" \
      -c "CREATE EXTENSION IF NOT EXISTS btree_gist;" \
      -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN CREATE ROLE app_runtime WITH LOGIN PASSWORD '$${APP_RUNTIME_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; END IF; END \$\$;" \
      -c "GRANT CONNECT ON DATABASE $${PGDATABASE} TO app_runtime;" \
      -c "GRANT USAGE ON SCHEMA public TO app_runtime;"
  EOT
}

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task_jobs.arn

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = var.image_uri
      essential = true
      command   = var.migrate_command

      environment = [
        { name = "ENVIRONMENT", value = var.environment_name },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
        { name = "RUNTIME_DATABASE_URL", valueFrom = var.runtime_database_url_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options   = local.jobs_log_options
      }
    }
  ])

  tags = var.tags
}

# --- Scheduled task definitions (targets for EventBridge Scheduler,
# modules/scheduler-alarms) --- see variables.tf's own comment on
# verify_audit_chain_command/retry_calendar_sync_command for the flagged
# backend-gap this module does NOT paper over.

resource "aws_ecs_task_definition" "verify_audit_chain" {
  family                   = "${var.name_prefix}-verify-audit-chain"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task_jobs.arn

  container_definitions = jsonencode([
    {
      name      = "verify-audit-chain"
      image     = var.image_uri
      essential = true
      command   = var.verify_audit_chain_command

      environment = [
        { name = "ENVIRONMENT", value = var.environment_name },
        { name = "AWS_DEFAULT_REGION", value = var.aws_default_region },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
        { name = "RUNTIME_DATABASE_URL", valueFrom = var.runtime_database_url_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options   = local.jobs_log_options
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_task_definition" "retry_calendar_sync" {
  family                   = "${var.name_prefix}-retry-calendar-sync"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task_jobs.arn

  container_definitions = jsonencode([
    {
      name      = "retry-calendar-sync"
      image     = var.image_uri
      essential = true
      command   = var.retry_calendar_sync_command

      environment = [
        { name = "ENVIRONMENT", value = var.environment_name },
        { name = "AWS_DEFAULT_REGION", value = var.aws_default_region },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
        { name = "RUNTIME_DATABASE_URL", valueFrom = var.runtime_database_url_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options   = local.jobs_log_options
      }
    }
  ])

  tags = var.tags
}
