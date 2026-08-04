# RDS Postgres Single-AZ + PITR (design.md §20.1/§20.2, ADR-20): "Single-AZ
# arriesga disponibilidad (failover de minutos), NO durabilidad (PITR
# protege el dato)". Multi-AZ is a documented upgrade trigger (§20.4), not
# built here.
#
# --- Credentials: composed DSNs, not `manage_master_user_password` ---
#
# `backend/app/config.py`'s `Settings.database_url` / `runtime_database_url`
# each expect ONE composed DSN string via a plain env var (`app/db.py`
# constructs both `AsyncEngine`s from those two strings at import time,
# unconditionally -- see that module's own docstring). AWS's native
# `manage_master_user_password = true` (RDS-managed password, Terraform
# never sees the plaintext) is the more modern pattern, but it only exposes
# discrete username/password/host/port fields via a Secrets Manager JSON
# blob -- assembling a single DSN from that at runtime would require
# `backend/app/config.py`/`app/db.py` to change (fetch-and-compose instead
# of read-one-env-var), which is backend-code scope explicitly out of this
# IaC-only task.
#
# So: Terraform generates BOTH the master password AND the `app_runtime`
# role's password itself (`random_password`), composes the two full DSNs,
# and stores those composed strings as their own Secrets Manager secrets,
# consumed by `modules/ecs` via the ECS task definition's `secrets` block --
# zero backend code changes, `Settings` keeps reading one plain env var
# exactly like it does today.
#
# **Known, deliberate tradeoff, not an oversight:** both passwords and both
# composed DSNs are known to Terraform and therefore live in Terraform
# state in PLAINTEXT. This mandates an encrypted remote backend (S3 with
# SSE-KMS + DynamoDB lock) with tightly restricted IAM access to the state
# bucket/table -- see envs/prod/backend.tf. A future task should move
# `Settings` to fetch/assemble `DATABASE_URL`/`RUNTIME_DATABASE_URL` from
# Secrets Manager JSON fields at runtime instead (avoids the full DSN ever
# touching Terraform state), matching the `manage_master_user_password`
# pattern -- not done here since it is backend-code scope.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-db-subnets" })
}

resource "random_password" "master" {
  length  = 32
  special = false
}

resource "random_password" "app_runtime" {
  length  = 32
  special = false
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.master_username
  password = random_password.master.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.rds_security_group_id]
  publicly_accessible    = false

  # design.md §20.2 ADR: Single-AZ day-1, PITR covers durability;
  # Multi-AZ is a documented upgrade trigger (§20.4), not day-1.
  multi_az = false

  backup_retention_period = var.backup_retention_days
  copy_tags_to_snapshot   = true
  deletion_protection     = var.deletion_protection
  skip_final_snapshot     = var.skip_final_snapshot
  final_snapshot_identifier = (
    var.skip_final_snapshot ? null : "${var.name_prefix}-db-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"
  )

  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })

  lifecycle {
    ignore_changes = [final_snapshot_identifier]
  }
}

locals {
  database_url         = "postgresql+asyncpg://${var.master_username}:${urlencode(random_password.master.result)}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${var.db_name}"
  runtime_database_url = "postgresql+asyncpg://app_runtime:${urlencode(random_password.app_runtime.result)}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${var.db_name}"
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.secret_name_prefix}/database-url"
  description             = "Composed DSN for the migrations/master role (backend/app/config.py Settings.database_url). Terraform-generated."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}

resource "aws_secretsmanager_secret" "runtime_database_url" {
  name                    = "${var.secret_name_prefix}/runtime-database-url"
  description             = "Composed DSN for the RLS-enforced app_runtime role (backend/app/config.py Settings.runtime_database_url). Terraform-generated."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "runtime_database_url" {
  secret_id     = aws_secretsmanager_secret.runtime_database_url.id
  secret_string = local.runtime_database_url
}

# Plain master password (not a full DSN) -- consumed only by the bootstrap
# ECS task's `PGPASSWORD` (libpq env var convention, avoids parsing the
# composed DSN back apart in a shell script).
resource "aws_secretsmanager_secret" "master_password" {
  name                    = "${var.secret_name_prefix}/db-master-password"
  description             = "Plain master role password, consumed only by the bootstrap ECS task. Terraform-generated."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "master_password" {
  secret_id     = aws_secretsmanager_secret.master_password.id
  secret_string = random_password.master.result
}

# Plain app_runtime password (not a full DSN) -- consumed only by the
# bootstrap ECS task's `CREATE ROLE ... PASSWORD` step
# (infra/postgres/init/02_app_runtime_role.sql's RDS equivalent), never by
# the API itself.
resource "aws_secretsmanager_secret" "app_runtime_password" {
  name                    = "${var.secret_name_prefix}/db-app-runtime-password"
  description             = "Plain app_runtime role password, consumed only by the bootstrap ECS task. Terraform-generated."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "app_runtime_password" {
  secret_id     = aws_secretsmanager_secret.app_runtime_password.id
  secret_string = random_password.app_runtime.result
}
