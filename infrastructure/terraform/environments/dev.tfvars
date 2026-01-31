# OpenRadiomics - Development Environment Variables

environment = "dev"
aws_region  = "us-east-1"

# Database
db_name              = "openradiomics"
db_username          = "postgres"
db_instance_class    = "db.t3.micro"
db_allocated_storage = 20
db_engine_version    = "15"

# Security
# Your home IP address (Samir's house)
# To update: curl -s https://checkip.amazonaws.com
allowed_ip = "100.1.237.100/32"

# TODO: Before production launch, update security group to allow:
#   - Application server IPs (Lambda/ECS/EC2)
#   - VPN or bastion host for admin access
#   - Remove direct public access (publicly_accessible = false in rds.tf)

# Project
project_name = "openradiomics"
