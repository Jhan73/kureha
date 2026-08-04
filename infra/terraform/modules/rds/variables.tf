variable "name_prefix" {
  description = "Prefix for RDS/hyphen-style AWS resource identifiers, e.g. \"kureha-prod\" (RDS identifiers reject \"/\")."
  type        = string
}

variable "secret_name_prefix" {
  description = "Prefix for Secrets Manager secret names, e.g. \"kureha/prod\" (slash-separated, matching infra/localstack/init's kureha/dev/kek convention) -- deliberately a SEPARATE variable from name_prefix, not reused, since aws_db_instance.identifier/aws_db_subnet_group.name reject \"/\"."
  type        = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "rds_security_group_id" {
  type = string
}

variable "db_name" {
  type    = string
  default = "kureha"
}

variable "master_username" {
  description = "Postgres bootstrap/superuser role, equivalent to docker-compose.yml's `app_user` (design.md §4.2 -- NOT the RLS-restricted role)."
  type        = string
  default     = "app_master"
}

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "instance_class" {
  description = "design.md §20.5: sized for ~13 connections/instance (10 app pool + 3 checkpointer) x N ECS instances, well under db.t3.medium's ~100 connection limit."
  type        = string
  default     = "db.t3.medium"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "backup_retention_days" {
  description = "Automated backups + PITR (design.md §20.2: durability, not availability, is what Single-AZ + backups protects)."
  type        = number
  default     = 7
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  description = "Set true only for throwaway/test environments."
  type        = bool
  default     = false
}

variable "recovery_window_in_days" {
  description = "Secrets Manager deletion recovery window for the credential secrets this module creates."
  type        = number
  default     = 7
}

variable "tags" {
  type    = map(string)
  default = {}
}
