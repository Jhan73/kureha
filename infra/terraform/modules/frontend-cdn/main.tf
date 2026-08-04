# S3 + CloudFront frontend tier (design.md §20.1): "CloudFront sirve solo
# assets estaticos... no se enruta trafico de API por CloudFront". Own tier,
# separate from the backend (ALB+WAF+ECS+RDS) -- no compute added.

resource "aws_s3_bucket" "spa" {
  bucket = coalesce(var.bucket_name, "${var.name_prefix}-spa")

  tags = merge(var.tags, { Name = "${var.name_prefix}-spa" })
}

resource "aws_s3_bucket_public_access_block" "spa" {
  bucket = aws_s3_bucket.spa.id

  block_public_acls       = true
  block_public_policy     = false # bucket policy below is scoped to CloudFront's OAC only, not public
  ignore_public_acls      = true
  restrict_public_buckets = false
}

resource "aws_s3_bucket_versioning" "spa" {
  bucket = aws_s3_bucket.spa.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_cloudfront_origin_access_control" "spa" {
  name                              = "${var.name_prefix}-spa-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Next.js `output: "export"` (frontend/next.config.ts) emits per-route
# `<route>.html` files (e.g. `out/portal/chat.html`), NOT `<route>/
# index.html` -- a bare S3/CloudFront GET for `/portal/chat` (no
# extension) would 404 without this rewrite. Standard documented pattern
# for a Next.js static export served from S3+CloudFront: a CloudFront
# Function on viewer-request appends `.html` (or `index.html` for a
# trailing-slash path) before the S3 origin ever sees the request.
resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "${var.name_prefix}-spa-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Appends .html to extension-less URIs for Next.js static export routing"
  publish = true

  code = <<-EOT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;

      if (uri.indexOf('.') === -1) {
        if (uri.endsWith('/')) {
          request.uri = uri + 'index.html';
        } else {
          request.uri = uri + '.html';
        }
      }

      return request;
    }
  EOT
}

resource "aws_cloudfront_distribution" "spa" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  price_class         = var.price_class
  aliases             = var.domain_aliases

  origin {
    domain_name              = aws_s3_bucket.spa.bucket_regional_domain_name
    origin_id                = "s3-spa"
    origin_access_control_id = aws_cloudfront_origin_access_control.spa.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "s3-spa"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    # AWS-managed "CachingOptimized" policy -- static assets, long TTL.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  # Next static export's own 404.html, matching design.md's "solo assets
  # estaticos" scope -- no server-side routing to fall back on.
  custom_error_response {
    error_code         = 403 # S3 returns 403, not 404, for a missing key behind an OAC-restricted bucket
    response_code      = 404
    response_page_path = "/404.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 404
    response_page_path = "/404.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.cloudfront_acm_certificate_arn == null
    acm_certificate_arn            = var.cloudfront_acm_certificate_arn
    ssl_support_method             = var.cloudfront_acm_certificate_arn == null ? null : "sni-only"
    minimum_protocol_version       = var.cloudfront_acm_certificate_arn == null ? null : "TLSv1.2_2021"
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-spa-cdn" })
}

data "aws_iam_policy_document" "spa_bucket_policy" {
  statement {
    sid       = "AllowCloudFrontOACRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.spa.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.spa.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "spa" {
  bucket = aws_s3_bucket.spa.id
  policy = data.aws_iam_policy_document.spa_bucket_policy.json
}
