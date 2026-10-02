# AWS-native starter for the governance console.
# STATUS: starter template, not yet applied to a live account — run
# `terraform init && terraform validate && terraform plan` and review before apply.
#
# Local component                      -> AWS-native equivalent created here
# govconsole serve (FastAPI)            -> App Runner service from an ECR image
# SQLite events store                   -> Aurora PostgreSQL Serverless v2 (DATABASE_URL from the managed secret)
# GOVERNANCE_INGEST/ADMIN_TOKEN env     -> Secrets Manager secrets
# (none)                                -> S3 events archive with Object Lock (OBS-03), for a Firehose stream
# kill switch table                     -> AppConfig application + feature-flag profile (optional path)

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "governance-console", owner = var.owner } }
}

data "aws_caller_identity" "me" {}

locals { prefix = "govconsole-${var.env}" }

# ---------- secrets (SEC-01)
resource "random_password" "ingest" {
  length  = 40
  special = false
}
resource "random_password" "admin" {
  length  = 40
  special = false
}
resource "aws_secretsmanager_secret" "ingest" { name = "${local.prefix}/ingest-token" }
resource "aws_secretsmanager_secret_version" "ingest" {
  secret_id     = aws_secretsmanager_secret.ingest.id
  secret_string = random_password.ingest.result
}
resource "aws_secretsmanager_secret" "admin" { name = "${local.prefix}/admin-token" }
resource "aws_secretsmanager_secret_version" "admin" {
  secret_id     = aws_secretsmanager_secret.admin.id
  secret_string = random_password.admin.result
}

# ---------- event store (Aurora PostgreSQL Serverless v2)
resource "aws_db_subnet_group" "db" {
  name       = "${local.prefix}-db"
  subnet_ids = var.private_subnet_ids
}
resource "aws_security_group" "db" {
  name   = "${local.prefix}-db"
  vpc_id = var.vpc_id
}
resource "aws_rds_cluster" "events" {
  cluster_identifier          = "${local.prefix}-events"
  engine                      = "aurora-postgresql"
  engine_mode                 = "provisioned"
  database_name               = "governance"
  master_username             = "govconsole"
  manage_master_user_password = true
  storage_encrypted           = true
  db_subnet_group_name        = aws_db_subnet_group.db.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  backup_retention_period     = 35
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.prefix}-final"
  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 4
  }
}
resource "aws_rds_cluster_instance" "events" {
  cluster_identifier = aws_rds_cluster.events.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.events.engine
}

# ---------- long-term archive (OBS-03): S3 with Object Lock for a Firehose stream
resource "aws_s3_bucket" "archive" {
  bucket              = "${local.prefix}-events-${data.aws_caller_identity.me.account_id}"
  object_lock_enabled = true
}
resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_object_lock_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.retention_days
    }
  }
}

# ---------- console service (App Runner)
resource "aws_iam_role" "apprunner_instance" {
  name = "${local.prefix}-instance"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "tasks.apprunner.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "apprunner_secrets" {
  role = aws_iam_role.apprunner_instance.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = ["secretsmanager:GetSecretValue"],
    Resource = [aws_secretsmanager_secret.ingest.arn, aws_secretsmanager_secret.admin.arn,
                aws_rds_cluster.events.master_user_secret[0].secret_arn] }] })
}
resource "aws_iam_role" "apprunner_ecr" {
  name = "${local.prefix}-ecr"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "build.apprunner.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "apprunner_ecr" {
  role       = aws_iam_role.apprunner_ecr.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}
resource "aws_apprunner_vpc_connector" "db" {
  vpc_connector_name = "${local.prefix}-db"
  subnets            = var.private_subnet_ids
  security_groups    = [aws_security_group.db.id]
}
resource "aws_apprunner_service" "console" {
  service_name = local.prefix
  source_configuration {
    authentication_configuration { access_role_arn = aws_iam_role.apprunner_ecr.arn }
    image_repository {
      image_identifier      = var.image_uri
      image_repository_type = "ECR"
      image_configuration {
        port = "8600"
        runtime_environment_secrets = {
          GOVERNANCE_INGEST_TOKEN = aws_secretsmanager_secret.ingest.arn
          GOVERNANCE_ADMIN_TOKEN  = aws_secretsmanager_secret.admin.arn
          # DATABASE_URL: build it from the RDS-managed secret (host, user, password) in an entrypoint script
        }
      }
    }
  }
  instance_configuration { instance_role_arn = aws_iam_role.apprunner_instance.arn }
  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.db.arn
    }
  }
}

# ---------- optional: kill switch as AppConfig feature flags (read by workflows via the AppConfig agent)
resource "aws_appconfig_application" "governance" { name = local.prefix }
resource "aws_appconfig_environment" "prod" {
  name           = var.env
  application_id = aws_appconfig_application.governance.id
}
resource "aws_appconfig_configuration_profile" "kill_switch" {
  application_id = aws_appconfig_application.governance.id
  name           = "workflow-kill-switch"
  location_uri   = "hosted"
  type           = "AWS.AppConfig.FeatureFlags"
}

# ---------- spend alert (COST-04) for the console's own footprint
resource "aws_budgets_budget" "console" {
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:project$governance-console"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
