# The public HTTPS address of the pilot (D-39): a CloudFront distribution in
# front of the host, with the free *.cloudfront.net name and certificate. It
# hides the host address, and caching is off, so each request and each SSE
# stream reaches the app unchanged (the bearer token included). The origin
# is Caddy on the host over HTTPS, under the sslip.io name it holds a
# certificate for.

locals {
  origin_hostname = var.hostname != "" ? var.hostname : "${replace(aws_eip.keel.public_ip, ".", "-")}.sslip.io"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_response_headers_policy" "security" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "aws_cloudfront_distribution" "keel" {
  #checkov:skip=CKV_AWS_68:no WAF for a 1-month pilot; the app has its own rate limits and bearer tokens
  #checkov:skip=CKV2_AWS_47:no WAF for a 1-month pilot (see CKV_AWS_68)
  #checkov:skip=CKV_AWS_86:access logs need a logging bucket; the app keeps its own audit log
  #checkov:skip=CKV_AWS_310:one origin; the host is the only source of the pilot
  #checkov:skip=CKV_AWS_374:the pilot users are not limited by country
  #checkov:skip=CKV_AWS_174:the default *.cloudfront.net certificate fixes the TLS policy; a custom domain would set TLSv1.2_2021
  #checkov:skip=CKV2_AWS_42:the free *.cloudfront.net name and its default certificate are the point (D-39)
  #checkov:skip=CKV2_AWS_32:Managed-SecurityHeadersPolicy is attached
  enabled         = true
  is_ipv6_enabled = true
  comment         = "keel ${var.environment}"
  price_class     = "PriceClass_100"
  http_version    = "http2and3"

  origin {
    origin_id   = "keel-host"
    domain_name = local.origin_hostname

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id           = "keel-host"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    compress                   = false
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
