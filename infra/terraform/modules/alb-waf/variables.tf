variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "alb_security_group_id" {
  type = string
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener (must already be issued/validated in this region, out-of-band -- ACM DNS validation is not something Terraform should silently automate against a real hosted zone in this module)."
  type        = string
}

variable "app_container_port" {
  type    = number
  default = 8000
}

variable "health_check_path" {
  description = "ALB target-group health check path. FLAGGED GAP: no dedicated GET /health endpoint exists in backend/app yet. /openapi.json is exempt from AccessControlMiddleware (see app/main.py's _ACCESS_CONTROL_EXEMPT_PATH_PREFIXES) and returns 200 with no DB dependency, used here as an interim health-check target -- recommend a real /health endpoint in a future backend task."
  type        = string
  default     = "/openapi.json"
}

variable "waf_rate_limit_per_5min" {
  description = "WAF rate-based rule threshold: requests per 5-minute window per source IP (design.md §19 layer 1)."
  type        = number
  default     = 2000
}

variable "tags" {
  type    = map(string)
  default = {}
}
