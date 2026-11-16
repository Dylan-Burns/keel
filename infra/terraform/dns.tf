# The custom domain of the pilot (D-40): a Route 53 zone for var.domain_name,
# an ACM certificate in us-east-1 for the apex and www, and alias records to
# the CloudFront distribution. The registrar delegates to the 4 name servers
# of the zone (the name_servers output). With domain_name empty, nothing here
# exists and the pilot keeps the free *.cloudfront.net name.
#
# The certificate validates through DNS, so the delegation must be in place
# before the full apply: apply -target=aws_route53_zone.keel first, set the
# name servers at the registrar, then apply the rest (infra/README.md).

locals {
  custom_domain = var.domain_name != ""
  site_names    = local.custom_domain ? [var.domain_name, "www.${var.domain_name}"] : []
}

resource "aws_route53_zone" "keel" {
  #checkov:skip=CKV2_AWS_38:no DNSSEC for a 1-month pilot; the registrar would need the DS record and a KMS key
  #checkov:skip=CKV2_AWS_39:no query logging for a 1-month pilot; it needs a log group in us-east-1
  count = local.custom_domain ? 1 : 0

  name    = var.domain_name
  comment = "keel ${var.environment}"
}

resource "aws_acm_certificate" "keel" {
  count    = local.custom_domain ? 1 : 0
  provider = aws.us_east_1

  domain_name               = var.domain_name
  subject_alternative_names = ["www.${var.domain_name}"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Keyed by the names in the configuration, so the plan knows every key before
# the certificate exists; the values come from the certificate at apply time.
resource "aws_route53_record" "acm_validation" {
  for_each = toset(local.site_names)

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
  validation_record_fqdns = [
    for record in aws_route53_record.acm_validation : record.fqdn
  ]
}

# Apex and www, IPv4 and IPv6, as aliases of the distribution.
resource "aws_route53_record" "site" {
  for_each = {
    for pair in setproduct(local.site_names, ["A", "AAAA"]) :
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
  count = local.custom_domain ? 1 : 0

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
  count = local.custom_domain ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = var.domain_name
  type    = "MX"
  ttl     = 3600
  records = ["0 ."]
}

resource "aws_route53_record" "spf" {
  count = local.custom_domain ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = var.domain_name
  type    = "TXT"
  ttl     = 3600
  records = ["v=spf1 -all"]
}

resource "aws_route53_record" "dmarc" {
  count = local.custom_domain ? 1 : 0

  zone_id = aws_route53_zone.keel[0].zone_id
  name    = "_dmarc.${var.domain_name}"
  type    = "TXT"
  ttl     = 3600
  records = ["v=DMARC1; p=reject; sp=reject; adkim=s; aspf=s"]
}
