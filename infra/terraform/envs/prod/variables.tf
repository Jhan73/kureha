variable "environment" {
  description = "Environment name, used for resource naming and the API's ENVIRONMENT env var."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

# --- Network ---

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "app_container_port" {
  type    = number
  default = 8000
}

# --- RDS ---

variable "db_name" {
  type    = string
  default = "kureha"
}

variable "db_master_username" {
  type    = string
  default = "app_master"
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

variable "db_deletion_protection" {
  type    = bool
  default = true
}

variable "db_skip_final_snapshot" {
  type    = bool
  default = false
}

variable "secrets_recovery_window_in_days" {
  type    = number
  default = 7
}

# --- ALB/WAF ---

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the ALB's HTTPS listener, issued/validated in var.aws_region out-of-band."
  type        = string
}

variable "alb_health_check_path" {
  type    = string
  default = "/openapi.json"
}

variable "waf_rate_limit_per_5min" {
  type    = number
  default = 2000
}

# --- ECS ---

variable "backend_image_uri" {
  description = "Backend container image URI (ECR repo:tag), built from backend/Dockerfile. Set by the CI/CD pipeline, not committed here."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Real CloudFront/S3 SPA origin(s), comma-separated (design.md §20)."
  type        = string
}

variable "ecs_desired_count" {
  type    = number
  default = 2
}

variable "ecs_cpu" {
  type    = number
  default = 512
}

variable "ecs_memory" {
  type    = number
  default = 1024
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# --- Scheduler / alarms ---

variable "verify_schedule_expression" {
  type    = string
  default = "rate(1 hour)"
}

variable "retry_schedule_expression" {
  type    = string
  default = "rate(15 minutes)"
}

variable "alarm_email" {
  type    = string
  default = null
}

# --- Frontend CDN ---

variable "frontend_domain_aliases" {
  type    = list(string)
  default = []
}

variable "frontend_acm_certificate_arn" {
  description = "ACM certificate ARN for the CloudFront distribution -- MUST be in us-east-1, only used if frontend_domain_aliases is non-empty."
  type        = string
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}
