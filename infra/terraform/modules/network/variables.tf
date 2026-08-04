variable "name_prefix" {
  description = "Prefix for all network resource names, e.g. \"kureha-prod\"."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (design.md §20: VPC unica, region unica)."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the 2 public subnets (ALB + NAT only, design.md §20.2)."
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the 2 private subnets (ECS + RDS)."
  type        = list(string)
  default     = ["10.20.10.0/24", "10.20.11.0/24"]
}

variable "app_container_port" {
  description = "Port the ECS API container listens on (uvicorn, design.md §20.1)."
  type        = number
  default     = 8000
}

variable "tags" {
  type    = map(string)
  default = {}
}
