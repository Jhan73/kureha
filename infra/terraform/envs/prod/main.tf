# Root composition for the AWS deployment topology described in
# design.md §20 (ADR-20). See infra/terraform/README.md for the ordering
# runbook (network -> secrets/rds -> alb-waf -> ecs -> scheduler-alarms ->
# frontend-cdn, plus the bootstrap/migrate one-off tasks in between).

locals {
  name_prefix        = "kureha-${var.environment}"
  secret_name_prefix = "kureha/${var.environment}"

  common_tags = merge(var.tags, {
    Project     = "kureha"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

module "network" {
  source = "../../modules/network"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  app_container_port = var.app_container_port
  tags               = local.common_tags
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix             = local.secret_name_prefix
  recovery_window_in_days = var.secrets_recovery_window_in_days
  tags                    = local.common_tags
}

module "rds" {
  source = "../../modules/rds"

  name_prefix             = local.name_prefix
  secret_name_prefix      = local.secret_name_prefix
  private_subnet_ids      = module.network.private_subnet_ids
  rds_security_group_id   = module.network.rds_security_group_id
  db_name                 = var.db_name
  master_username         = var.db_master_username
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_storage
  backup_retention_days   = var.db_backup_retention_days
  deletion_protection     = var.db_deletion_protection
  skip_final_snapshot     = var.db_skip_final_snapshot
  recovery_window_in_days = var.secrets_recovery_window_in_days
  tags                    = local.common_tags
}

module "alb_waf" {
  source = "../../modules/alb-waf"

  name_prefix             = local.name_prefix
  vpc_id                  = module.network.vpc_id
  public_subnet_ids       = module.network.public_subnet_ids
  alb_security_group_id   = module.network.alb_security_group_id
  acm_certificate_arn     = var.acm_certificate_arn
  app_container_port      = var.app_container_port
  health_check_path       = var.alb_health_check_path
  waf_rate_limit_per_5min = var.waf_rate_limit_per_5min
  tags                    = local.common_tags
}

module "ecs" {
  source = "../../modules/ecs"

  name_prefix           = local.name_prefix
  aws_region            = var.aws_region
  environment_name      = var.environment
  private_subnet_ids    = module.network.private_subnet_ids
  ecs_security_group_id = module.network.ecs_security_group_id
  target_group_arn      = module.alb_waf.target_group_arn
  image_uri             = var.backend_image_uri
  container_port        = var.app_container_port
  desired_count         = var.ecs_desired_count
  cpu                   = var.ecs_cpu
  memory                = var.ecs_memory
  log_retention_days    = var.log_retention_days
  cors_allowed_origins  = var.cors_allowed_origins
  aws_default_region    = var.aws_region

  database_url_secret_arn          = module.rds.database_url_secret_arn
  runtime_database_url_secret_arn  = module.rds.runtime_database_url_secret_arn
  master_password_secret_arn       = module.rds.master_password_secret_arn
  app_runtime_password_secret_arn  = module.rds.app_runtime_password_secret_arn
  identity_access_token_secret_arn = module.secrets.identity_access_token_secret_arn
  calendar_oauth_state_secret_arn  = module.secrets.calendar_oauth_state_secret_arn
  google_oauth_secret_arn          = module.secrets.google_oauth_secret_arn
  supabase_secret_arn              = module.secrets.supabase_secret_arn
  anthropic_api_key_secret_arn     = module.secrets.anthropic_api_key_secret_arn
  kek_secret_arn                   = module.secrets.kek_secret_arn

  db_host            = module.rds.db_address
  db_port            = module.rds.db_port
  db_name            = module.rds.db_name
  db_master_username = module.rds.master_username

  tags = local.common_tags
}

module "scheduler_alarms" {
  source = "../../modules/scheduler-alarms"

  name_prefix           = local.name_prefix
  private_subnet_ids    = module.network.private_subnet_ids
  ecs_security_group_id = module.network.ecs_security_group_id
  cluster_arn           = module.ecs.cluster_arn
  execution_role_arn    = module.ecs.execution_role_arn
  task_jobs_role_arn    = module.ecs.task_jobs_role_arn

  verify_audit_chain_task_definition_arn  = module.ecs.verify_audit_chain_task_definition_arn
  retry_calendar_sync_task_definition_arn = module.ecs.retry_calendar_sync_task_definition_arn

  verify_schedule_expression = var.verify_schedule_expression
  retry_schedule_expression  = var.retry_schedule_expression
  alarm_email                = var.alarm_email

  tags = local.common_tags
}

module "frontend_cdn" {
  source = "../../modules/frontend-cdn"

  name_prefix                    = local.name_prefix
  domain_aliases                 = var.frontend_domain_aliases
  cloudfront_acm_certificate_arn = var.frontend_acm_certificate_arn
  tags                           = local.common_tags
}
