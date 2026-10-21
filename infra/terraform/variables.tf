variable "region" {
  description = "AWS region for the pilot host."
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name used in tags."
  type        = string
  default     = "pilot"
}

variable "instance_type" {
  description = "Instance type. 4 GB of memory is the minimum for the embedding and reranker models."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  description = "Root volume size in GB. The corpus, the index, and the model cache need about 10 GB."
  type        = number
  default     = 40
}

variable "ssh_key_name" {
  description = "Name of an existing EC2 key pair for administrative SSH."
  type        = string
}

variable "admin_cidr" {
  description = "CIDR allowed to reach SSH, for example your office or VPN egress /32."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a CIDR and must not be 0.0.0.0/0."
  }
}

variable "backup_bucket_name" {
  description = "Globally unique S3 bucket name for nightly backups."
  type        = string
}

variable "hostname" {
  description = "DNS name for the service, for example keel.example.com. Leave empty to skip the Route 53 record."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Hosted zone ID that owns the hostname. Leave empty to skip the Route 53 record."
  type        = string
  default     = ""
}
