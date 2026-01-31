# OpenRadiomics - S3 Storage Configuration

# S3 bucket for DICOM files
resource "aws_s3_bucket" "dicom" {
  bucket = "${var.project_name}-${var.environment}-dicom-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project_name}-${var.environment}-dicom"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "dicom" {
  bucket = aws_s3_bucket.dicom.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable versioning for data protection
resource "aws_s3_bucket_versioning" "dicom" {
  bucket = aws_s3_bucket.dicom.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "dicom" {
  bucket = aws_s3_bucket.dicom.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Lifecycle rules - transition old versions to cheaper storage
resource "aws_s3_bucket_lifecycle_configuration" "dicom" {
  bucket = aws_s3_bucket.dicom.id

  rule {
    id     = "archive-old-versions"
    status = "Enabled"

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# CORS configuration for browser access (if needed for direct uploads)
resource "aws_s3_bucket_cors_configuration" "dicom" {
  bucket = aws_s3_bucket.dicom.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"] # Restrict in production
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# IAM policy for app access to S3
resource "aws_iam_policy" "s3_dicom_access" {
  name        = "${var.project_name}-${var.environment}-s3-dicom-access"
  description = "Allow read access to DICOM S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.dicom.arn,
          "${aws_s3_bucket.dicom.arn}/*"
        ]
      }
    ]
  })
}

# IAM role for App Runner
resource "aws_iam_role" "apprunner" {
  name = "${var.project_name}-${var.environment}-apprunner-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "tasks.apprunner.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_s3" {
  role       = aws_iam_role.apprunner.name
  policy_arn = aws_iam_policy.s3_dicom_access.arn
}

# ECR repository for Docker images
resource "aws_ecr_repository" "app" {
  name                 = "${var.project_name}-${var.environment}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ecr"
  }
}

# ECR lifecycle policy - keep last 10 images
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
