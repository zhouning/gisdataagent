# =============================================================================
# GIS Data Agent — Terraform Infrastructure
#
# Defines the core infrastructure for production deployment.
# Supports: Huawei Cloud (primary), AWS (secondary), GCP (secondary)
#
# Usage:
#   terraform init
#   terraform plan -var-file="production.tfvars"
#   terraform apply -var-file="production.tfvars"
# =============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    # Huawei Cloud provider (primary)
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = "~> 1.60"
    }
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "region" {
  description = "Cloud region"
  type        = string
  default     = "cn-south-1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "gis-data-agent"
}

variable "environment" {
  description = "Deployment environment (dev/staging/production)"
  type        = string
  default     = "production"
}

variable "db_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "obs_bucket" {
  description = "OBS bucket name for data lake"
  type        = string
  default     = "gisdatalake"
}

variable "app_image" {
  description = "Docker image for the application"
  type        = string
  default     = "gis-data-agent:latest"
}

# ---------------------------------------------------------------------------
# Provider Configuration
# ---------------------------------------------------------------------------

provider "huaweicloud" {
  region = var.region
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

resource "huaweicloud_vpc" "agent_vpc" {
  name = "${var.project_name}-${var.environment}-vpc"
  cidr = "10.0.0.0/16"
}

resource "huaweicloud_vpc_subnet" "agent_subnet" {
  name       = "${var.project_name}-${var.environment}-subnet"
  cidr       = "10.0.1.0/24"
  vpc_id     = huaweicloud_vpc.agent_vpc.id
  gateway_ip = "10.0.1.1"
}

# ---------------------------------------------------------------------------
# PostgreSQL (RDS for PostGIS)
# ---------------------------------------------------------------------------

resource "huaweicloud_rds_instance" "agent_db" {
  name              = "${var.project_name}-${var.environment}-db"
  flavor            = "rds.pg.c6.large.4"  # 2 vCPU, 8 GB
  ha_replication_mode = null  # Single instance for cost
  vpc_id            = huaweicloud_vpc.agent_vpc.id
  subnet_id         = huaweicloud_vpc_subnet.agent_subnet.id

  db {
    type     = "PostgreSQL"
    version  = "16"
    password = var.db_password
  }

  volume {
    type = "CLOUDSSD"
    size = 100  # GB
  }

  backup_strategy {
    start_time = "02:00-03:00"
    keep_days  = 7
  }

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# OBS Bucket (Data Lake)
# ---------------------------------------------------------------------------

resource "huaweicloud_obs_bucket" "data_lake" {
  bucket        = var.obs_bucket
  acl           = "private"
  force_destroy = false

  versioning = true

  lifecycle_rule {
    name    = "archive-old-data"
    enabled = true

    transition {
      days          = 90
      storage_class = "WARM"
    }
    transition {
      days          = 365
      storage_class = "COLD"
    }
  }

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "vpc_id" {
  value = huaweicloud_vpc.agent_vpc.id
}

output "db_endpoint" {
  value     = huaweicloud_rds_instance.agent_db.fixed_ip
  sensitive = false
}

output "obs_bucket" {
  value = huaweicloud_obs_bucket.data_lake.bucket
}
