variable "name_prefix" {
  type = string
}

variable "bucket_name" {
  description = "S3 bucket name for the SPA's static-export build. Bucket names are globally unique -- override the default if it collides."
  type        = string
  default     = null
}

variable "domain_aliases" {
  description = "Optional custom domain(s) for the CloudFront distribution (design.md §20.1). Leave empty to use the default *.cloudfront.net domain."
  type        = list(string)
  default     = []
}

variable "cloudfront_acm_certificate_arn" {
  description = "ACM certificate ARN for domain_aliases -- MUST be issued in us-east-1 regardless of the deployment region (CloudFront's own hard requirement). Required only if domain_aliases is non-empty."
  type        = string
  default     = null
}

variable "price_class" {
  type    = string
  default = "PriceClass_100" # US/Canada/Europe -- MVP is Peru-only traffic, no need for the global edge tier.
}

variable "tags" {
  type    = map(string)
  default = {}
}
