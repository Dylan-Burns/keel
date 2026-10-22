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
  description = "Public HTTPS address of the pilot (the free *.cloudfront.net name); the GitHub variable KEEL_PUBLIC_URL."
  value       = "https://${aws_cloudfront_distribution.keel.domain_name}"
}
