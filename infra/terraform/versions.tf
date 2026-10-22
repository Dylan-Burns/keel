terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  # State in S3 with a native lock file (ci.tf creates the bucket). Values
  # come from backend.hcl: terraform init -backend-config=backend.hcl
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "keel"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
