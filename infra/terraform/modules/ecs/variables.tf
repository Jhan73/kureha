variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "environment_name" {
  description = "Value for the API's ENVIRONMENT env var (backend/app/config.py Settings.environment), e.g. \"production\"."
  type        = string
  default     = "production"
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type = string
}

variable "target_group_arn" {
  description = "ALB target group the API service registers into (modules/alb-waf)."
  type        = string
}

variable "image_uri" {
  description = "Backend container image URI (design.md §1/§20.1: same image serves the API, the agent runtime, and every scheduled/one-off job), e.g. an ECR repo:tag such as <account>.dkr.ecr.<region>.amazonaws.com/kureha-backend:latest. Built from backend/Dockerfile (production target, not Dockerfile.dev)."
  type        = string
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "desired_count" {
  type    = number
  default = 2
}

variable "cpu" {
  description = "Fargate task-level vCPU units (256=.25vCPU, 512=.5vCPU, 1024=1vCPU, ...)."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task-level memory (MiB), must be a valid cpu/memory combination."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "cors_allowed_origins" {
  description = "backend/app/config.py Settings.cors_allowed_origins -- the real CloudFront/S3 SPA origin (design.md §20: never same-origin with the backend)."
  type        = string
}

variable "aws_default_region" {
  type    = string
  default = "us-east-1"
}

# --- Secret ARNs injected into task definitions via the `secrets` block
# (resolved by the EXECUTION role at container startup, per AWS's own ECS
# constraint -- see this module's main.tf comment on IAM). ---

variable "database_url_secret_arn" {
  type = string
}

variable "runtime_database_url_secret_arn" {
  type = string
}

variable "master_password_secret_arn" {
  description = "Plain master password (PGPASSWORD), consumed only by the bootstrap task."
  type        = string
}

variable "app_runtime_password_secret_arn" {
  description = "Plain app_runtime password, consumed only by the bootstrap task's CREATE ROLE step."
  type        = string
}

variable "db_host" {
  description = "RDS endpoint address (modules/rds db_address output), used by the bootstrap task's PGHOST."
  type        = string
}

variable "db_port" {
  type    = number
  default = 5432
}

variable "db_name" {
  type = string
}

variable "db_master_username" {
  type = string
}

variable "identity_access_token_secret_arn" {
  type = string
}

variable "calendar_oauth_state_secret_arn" {
  type = string
}

variable "google_oauth_secret_arn" {
  description = "JSON secret with client_id/client_secret keys (modules/secrets)."
  type        = string
}

variable "supabase_secret_arn" {
  description = "JSON secret with url/anon_key keys (modules/secrets)."
  type        = string
}

variable "anthropic_api_key_secret_arn" {
  type = string
}

variable "kek_secret_arn" {
  description = "Fetched by the app itself at runtime via boto3 (AesGcmVault), not injected as an env var -- only the TASK role (not the execution role) needs read access to this one."
  type        = string
}

variable "db_app_runtime_username" {
  type    = string
  default = "app_runtime"
}

variable "extra_environment" {
  description = "Additional plain (non-secret) env vars to merge into the API container's environment, e.g. LLM_FAST_MODEL overrides. Empty by default -- config.py's own defaults cover everything not listed explicitly in this module."
  type        = map(string)
  default     = {}
}

# --- One-off / scheduled job commands ---
# FLAGGED GAP (tasks.md 16.2 closure note): `backend/app/` has NO CLI
# entrypoint for either job today -- confirmed by grepping the whole
# backend tree for `verify_chain`/`hash_chain`/an `app/jobs/` package/a
# `[project.scripts]` entry: none exist. The audit hash-chain verify job
# (design.md §4.3) has NO use-case-level implementation at all (not even a
# unit-tested class, unlike the calendar retry job). The calendar retry job
# DOES have a real, tested use case (`RetryPendingCalendarSyncs`, tasks.md
# 9.5) but no composition-root builder, no CLI wrapper, and no per-tenant
# iteration loop to run it for every tenant unattended. These commands are
# placeholders shaped like the entrypoint this Terraform module expects
# once that backend work exists -- Terraform cannot and does not fabricate
# the missing application code.
variable "verify_audit_chain_command" {
  type    = list(string)
  default = ["python", "-m", "app.jobs.verify_audit_chain"]
}

variable "retry_calendar_sync_command" {
  type    = list(string)
  default = ["python", "-m", "app.jobs.retry_calendar_sync"]
}

variable "migrate_command" {
  description = "Runs Alembic migrations using the real backend image (design.md §20.1). Must run AFTER the bootstrap task (see aws_ecs_task_definition.bootstrap_db's own comment)."
  type        = list(string)
  default     = ["uv", "run", "alembic", "upgrade", "head"]
}

variable "tags" {
  type    = map(string)
  default = {}
}
