# OpenRadiomics - Terraform Variables

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "openradiomics"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "PostgreSQL master password (use TF_VAR_db_password environment variable)"
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro" # Free tier eligible
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20 # Free tier: up to 20GB
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "15"
}

variable "allowed_ip" {
  description = "IP address allowed to access RDS (CIDR notation, e.g., 1.2.3.4/32)"
  type        = string
  default     = "0.0.0.0/0" # WARNING: Open to all - restrict in production!
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "openradiomics"
}
