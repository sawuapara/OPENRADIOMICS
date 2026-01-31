# OpenRadiomics - Terraform Configuration
# AWS RDS PostgreSQL Infrastructure

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local backend for now - migrate to S3 for production
  # backend "s3" {
  #   bucket         = "openradiomics-terraform-state"
  #   key            = "terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "OpenRadiomics"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Data source to get current AWS account ID and caller identity
data "aws_caller_identity" "current" {}

data "aws_region" "current" {}
