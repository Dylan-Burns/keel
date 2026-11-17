# The custom domain of the site (D-40). With dns_zone = "route53": a Route 53
# zone for var.domain_name,
# an ACM certificate in us-east-1 for the apex and www, and alias records to
# the CloudFront distribution. The registrar delegates to the 4 name servers
# of the zone (the name_servers output). With domain_name empty, nothing here
# exists and the site keeps the free *.cloudfront.net name.
#
# With dns_zone = "external" (Squarespace DNS): no zone; the certificate
# covers www only, and the dns_records_to_add output lists the records to
# add at the provider (the validation CNAME and www). The apex forwards to
# www at the provider.
#
# The certificate validates through DNS, so the delegation must be in place
# before the full apply: apply -target=aws_route53_zone.keel first, set the
# name servers at the registrar, then apply the rest (infra/README.md).

locals {
  custom_domain = var.domain_name != ""
  route53       = local.custom_domain && var.dns_zone == "route53"
  # With external DNS the apex cannot alias CloudFront (no ALIAS record at
  # most providers), so only www is served and the apex forwards to it.
  site_names = (
    !local.custom_domain ? [] :
    local.route53 ? [var.domain_name, "www.${var.domain_name}"] :
    ["www.${var.domain_name}"]
  )
  route53_names = local.route53 ? local.site_names : []
}

resource "aws_route53_zone" "keel" {
  #checkov:skip=CKV2_AWS_38:no DNSSEC for a 1-month pilot; the registrar would need the DS record and a KMS key
  #checkov:skip=CKV2_AWS_39:no query logging for a 1-month pilot; it needs a log group in us-east-1
  count = local.route53 ? 1 : 0

  name    = var.domain_name
  comment = "keel ${var.environment}"
}

resource "aws_acm_certificate" "keel" {
  count    = local.custom_domain ? 1 : 0
  provider = aws.us_east_1

  domain_name               = local.site_names[0]
  subject_alternative_names = slice(local.site_names, 1, length(local.site_names))
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Keyed by the names in the configuration, so the plan knows every key before
# the certificate exists; the values come from the certificate at apply time.
resource "aws_route53_record" "acm_validation" {
  for_each = toset(local.route53_names)

  zone_id = aws_route53_zone.keel[0].zone_id
  name = one([
    for option in aws_acm_certificate.keel[0].domain_validation_options :
    option.resource_record_name if option.domain_name == each.key
  ])
  type = one([
    for option in aws_acm_certificate.keel[0].domain_validation_options :
    option.resource_record_type if option.domain_name == each.key
  ])
  ttl = 300
  records = [one([
    for option in aws_acm_certificate.keel[0].domain_validation_options :
    option.resource_record_value if option.domain_name == each.key
  ])]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "keel" {
  count    = local.custom_domain ? 1 : 0
  provider = aws.us_east_1

  certificate_arn = aws_acm_certificate.keel[0].arn
  # With external DNS this waits until the validation records of the
  # dns_records_to_add output are live at the provider.
  validation_record_fqdns = local.route53 ? [
    for record in aws_route53_record.acm_validation : record.fqdn
  ] : null

  timeouts {
    create = "2h"
  }
}

# Apex and www, IPv4 and IPv6, as aliases of the distribution.
resource "aws_route53_record" "site" {
  for_each = {
    for pair in setproduct(local.route53_names, ["A", "AAAA"]) :
    "${pair[0]}/${pair[1]}" => { name = pair[0], type = pair[1] }
  }

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = each.value.name
  type    = each.value.type

  alias {
    name                   = aws_cloudfront_distribution.keel.domain_name
    zone_id                = aws_cloudfront_distribution.keel.hosted_zone_id
    evaluate_target_health = false
  }
}

# Only ACM issues certificates for the zone (Let's Encrypt as well, for a
# Caddy host name under the domain later).
resource "aws_route53_record" "caa" {
  count = local.route53 ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = var.domain_name
  type    = "CAA"
  ttl     = 3600
  records = [
    "0 issue \"amazon.com\"",
    "0 issue \"letsencrypt.org\"",
  ]
}

# The domain sends and receives no mail: a null MX (RFC 7505), an SPF record
# that allows no sender, and a DMARC policy that rejects, so nobody can spoof
# mail from it.
resource "aws_route53_record" "null_mx" {
  count = local.route53 ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = var.domain_name
  type    = "MX"
  ttl     = 3600
  records = ["0 ."]
}

resource "aws_route53_record" "spf" {
  count = local.route53 ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = var.domain_name
  type    = "TXT"
  ttl     = 3600
  records = ["v=spf1 -all"]
}

resource "aws_route53_record" "dmarc" {
  count = local.route53 ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = "_dmarc.${var.domain_name}"
  type    = "TXT"
  ttl     = 3600
  records = ["v=DMARC1; p=reject; sp=reject; adkim=s; aspf=s"]
}
