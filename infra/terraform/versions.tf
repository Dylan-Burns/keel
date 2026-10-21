terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.69"
    }
  }

  # Remote state for a team: uncomment and set the bucket before `init`.
  # backend "s3" {
  #   bucket         = "keel-terraform-state"
  #   key            = "pilot/terraform.tfstate"
  #   region         = "us-west-2"
  #   dynamodb_table = "keel-terraform-locks"
  #   encrypt        = true
  # }
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
