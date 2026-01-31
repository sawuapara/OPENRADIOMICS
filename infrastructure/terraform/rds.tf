# OpenRadiomics - RDS PostgreSQL Configuration
#
# TODO [PRODUCTION LAUNCH]: Before going to production:
#   1. Set publicly_accessible = false (line ~30)
#   2. Update security group to only allow app servers (vpc.tf)
#   3. Set deletion_protection = true
#   4. Set skip_final_snapshot = false
#   5. Consider Multi-AZ deployment for high availability
#

# RDS PostgreSQL Instance
resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-${var.environment}-db"

  # Engine
  engine               = "postgres"
  engine_version       = var.db_engine_version
  instance_class       = var.db_instance_class
  parameter_group_name = aws_db_parameter_group.postgres.name

  # Storage
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = 100 # Enable autoscaling up to 100GB
  storage_type          = "gp2"
  storage_encrypted     = true

  # Database
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  # Network
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = true # For dev access - disable in production
  port                   = 5432

  # Backup & Maintenance
  backup_retention_period   = 7
  backup_window             = "03:00-04:00"
  maintenance_window        = "Mon:04:00-Mon:05:00"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = true
  deletion_protection       = var.environment == "prod" ? true : false
  skip_final_snapshot       = var.environment == "dev" ? true : false
  final_snapshot_identifier = var.environment != "dev" ? "${var.project_name}-${var.environment}-final-snapshot" : null

  # Performance Insights (free tier includes 7 days)
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Logging
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  # Tags
  tags = {
    Name = "${var.project_name}-${var.environment}-postgres"
  }

  lifecycle {
    prevent_destroy = false # Set to true in production
  }
}

# Parameter Group for PostgreSQL
resource "aws_db_parameter_group" "postgres" {
  family = "postgres15"
  name   = "${var.project_name}-${var.environment}-pg15-params"

  # Optimize for JSONB queries (radiomics data)
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  parameter {
    name  = "log_statement"
    value = "ddl"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # Log queries taking > 1 second
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-pg15-params"
  }
}

# CloudWatch Alarms for RDS
resource "aws_cloudwatch_metric_alarm" "db_cpu" {
  alarm_name          = "${var.project_name}-${var.environment}-db-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Database CPU utilization is high"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-db-cpu-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${var.project_name}-${var.environment}-db-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120 # 5GB in bytes
  alarm_description   = "Database free storage is low"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-db-storage-alarm"
  }
}
