# OpenRadiomics - AWS App Runner Configuration

# App Runner service
resource "aws_apprunner_service" "app" {
  service_name = "${var.project_name}-${var.environment}"

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr.arn
    }

    image_repository {
      image_configuration {
        port = "5000"
        runtime_environment_variables = {
          ENVIRONMENT    = var.environment
          S3_BUCKET_NAME = aws_s3_bucket.dicom.bucket
          AWS_REGION     = var.aws_region
          # Database connection will be added when RDS is deployed
          # DATABASE_URL = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.endpoint}/${var.db_name}"
        }
      }
      image_identifier      = "${aws_ecr_repository.app.repository_url}:latest"
      image_repository_type = "ECR"
    }

    auto_deployments_enabled = true
  }

  instance_configuration {
    cpu               = "1024"  # 1 vCPU
    memory            = "2048"  # 2 GB
    instance_role_arn = aws_iam_role.apprunner.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/api/studies"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-apprunner"
  }

  depends_on = [
    aws_iam_role_policy_attachment.apprunner_ecr
  ]
}

# IAM role for App Runner to pull from ECR
resource "aws_iam_role" "apprunner_ecr" {
  name = "${var.project_name}-${var.environment}-apprunner-ecr-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr" {
  role       = aws_iam_role.apprunner_ecr.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}
