# AWS-native starter for eod-heartbeat.
# STATUS: starter template, not yet applied to a live account — run
# `terraform init && terraform validate && terraform plan` and review before apply.
#
# Local component                 -> AWS-native equivalent created here
# data/landing/ folders           -> S3 landing bucket (vendor/PB SFTP or S3 drops land here)
# embedded Postgres + pgvector    -> RDS PostgreSQL 16 (pgvector extension), credentials in Secrets Manager
# Airflow DAG (docker compose)    -> Amazon MWAA environment reading dags/ + requirements from S3
# mock / Anthropic explainer      -> Amazon Bedrock (InvokeModel / Converse, IAM-scoped to approved ARNs)
# alert outbox                    -> SNS topic (email / Slack via Chatbot / PagerDuty subscriptions)
# eodhb retention archive         -> S3 bucket with Object Lock (WORM) for audit archives (OBS-03)
# cost.monthly_alert_usd          -> AWS Budgets alert

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "eod-heartbeat", owner = var.owner, data_class = "fund-operations" } }
}

data "aws_caller_identity" "me" {}

locals {
  prefix = "eod-heartbeat-${var.env}"
  acct   = data.aws_caller_identity.me.account_id
}

# ---------- buckets: landing, MWAA (dags + requirements), WORM archive
resource "aws_s3_bucket" "landing" { bucket = "${local.prefix}-landing-${local.acct}" }
resource "aws_s3_bucket" "mwaa" { bucket = "${local.prefix}-mwaa-${local.acct}" }
resource "aws_s3_bucket" "archive" {
  bucket              = "${local.prefix}-archive-${local.acct}"
  object_lock_enabled = true
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { landing = aws_s3_bucket.landing.id, mwaa = aws_s3_bucket.mwaa.id, archive = aws_s3_bucket.archive.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "mwaa" {
  bucket = aws_s3_bucket.mwaa.id
  versioning_configuration { status = "Enabled" } # MWAA requires versioning
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    default_retention {
      mode = "COMPLIANCE" # nobody, including root, can delete before the retention date (OBS-03)
      days = var.log_retention_days
    }
  }
}

# ---------- RDS PostgreSQL 16 with pgvector
resource "aws_db_subnet_group" "db" {
  name       = "${local.prefix}-db"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "db" {
  name   = "${local.prefix}-db"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.mwaa.id]
  }
}

resource "aws_db_instance" "eod" {
  identifier                  = "${local.prefix}-pg"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.db_instance_class
  allocated_storage           = 50
  storage_encrypted           = true
  db_name                     = "eod"
  username                    = "eod_admin"
  manage_master_user_password = true # password generated and stored in Secrets Manager (SEC-01)
  db_subnet_group_name        = aws_db_subnet_group.db.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  backup_retention_period     = 14
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.prefix}-final"
  # pgvector: run `create extension vector;` once (eodhb does this on first connect)
}

# ---------- alerts
resource "aws_sns_topic" "alerts" {
  name              = "${local.prefix}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "oncall" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.oncall_email
}

# ---------- MWAA (managed Airflow)
resource "aws_security_group" "mwaa" {
  name   = "${local.prefix}-mwaa"
  vpc_id = var.vpc_id
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "mwaa" {
  name = "${local.prefix}-mwaa"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole",
    Principal = { Service = ["airflow.amazonaws.com", "airflow-env.amazonaws.com"] } }]
  })
}

resource "aws_iam_role_policy" "mwaa" {
  role = aws_iam_role.mwaa.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject*", "s3:GetBucket*", "s3:List*"], Resource = [aws_s3_bucket.mwaa.arn, "${aws_s3_bucket.mwaa.arn}/*", aws_s3_bucket.landing.arn, "${aws_s3_bucket.landing.arn}/*"] },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${aws_s3_bucket.archive.arn}/*"] },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_db_instance.eod.master_user_secret[0].secret_arn] },
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Converse"], Resource = var.approved_bedrock_model_arns },
      { Effect = "Allow", Action = ["sns:Publish"], Resource = [aws_sns_topic.alerts.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents", "logs:GetLogEvents", "logs:GetLogRecord", "logs:GetLogGroupFields", "logs:GetQueryResults", "logs:DescribeLogGroups"], Resource = "*" },
      { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*" },
      { Effect = "Allow", Action = ["sqs:ChangeMessageVisibility", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ReceiveMessage", "sqs:SendMessage"], Resource = "arn:aws:sqs:${var.region}:*:airflow-celery-*" },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey*", "kms:Encrypt"], NotResource = "arn:aws:kms:*:${local.acct}:key/*", Condition = { StringLike = { "kms:ViaService" = ["sqs.${var.region}.amazonaws.com"] } } }
    ]
  })
}

resource "aws_mwaa_environment" "eod" {
  name                 = local.prefix
  airflow_version      = var.airflow_version
  environment_class    = "mw1.small"
  execution_role_arn   = aws_iam_role.mwaa.arn
  source_bucket_arn    = aws_s3_bucket.mwaa.arn
  dag_s3_path          = "dags/"
  requirements_s3_path = "requirements.txt" # contains the eod-heartbeat wheel / git URL + dbt-postgres
  network_configuration {
    security_group_ids = [aws_security_group.mwaa.id]
    subnet_ids         = slice(var.private_subnet_ids, 0, 2)
  }
  airflow_configuration_options = {
    "core.load_examples" = "false"
  }
  logging_configuration {
    task_logs {
      enabled   = true
      log_level = "INFO"
    }
  }
  webserver_access_mode = "PRIVATE_ONLY"
}

# ---------- cost (COST-04)
resource "aws_budgets_budget" "monthly" {
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:project$eod-heartbeat"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.oncall_email]
  }
}
