output "public_ip" {
  description = "Elastic IP of the pilot host."
  value       = aws_eip.keel.public_ip
}

output "backup_bucket" {
  description = "S3 bucket that receives the nightly backups."
  value       = aws_s3_bucket.backups.bucket
}

output "ssh" {
  description = "SSH command for the host."
  value       = "ssh ubuntu@${aws_eip.keel.public_ip}"
}

output "instance_id" {
  description = "Instance ID; the GitHub variable KEEL_INSTANCE_ID for deploy-aws.yml."
  value       = aws_instance.keel.id
}

output "deploy_role_arn" {
  description = "Role that deploy-aws.yml assumes through GitHub OIDC; the GitHub variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.deploy.arn
}

output "hostname" {
  description = "HTTPS name without a DNS zone; the GitHub variable KEEL_HOSTNAME."
  value       = var.hostname != "" ? var.hostname : "${replace(aws_eip.keel.public_ip, ".", "-")}.sslip.io"
}

output "cloudfront_url" {
  description = "Public HTTPS address of the pilot: https://<domain_name> when set, else the free *.cloudfront.net name; the GitHub variable KEEL_PUBLIC_URL."
  value       = "https://${local.custom_domain ? local.site_names[0] : aws_cloudfront_distribution.keel.domain_name}"
}

output "name_servers" {
  description = "Route 53 name servers of domain_name; set them at the registrar. Empty without domain_name."
  value       = local.route53 ? aws_route53_zone.keel[0].name_servers : []
}

output "dns_records_to_add" {
  description = "With dns_zone = external: the records to add at the DNS provider (the certificate validation and www)."
  value = local.custom_domain && !local.route53 ? concat(
    [
      for option in aws_acm_certificate.keel[0].domain_validation_options : {
        type  = option.resource_record_type
        host  = trimsuffix(option.resource_record_name, ".${var.domain_name}.")
        value = trimsuffix(option.resource_record_value, ".")
      }
    ],
    [{
      type  = "CNAME"
      host  = "www"
      value = aws_cloudfront_distribution.keel.domain_name
    }],
  ) : []
}
