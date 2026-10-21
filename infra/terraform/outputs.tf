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
