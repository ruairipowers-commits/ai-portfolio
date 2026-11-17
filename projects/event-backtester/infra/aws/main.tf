# AWS-native starter for event-backtester.
# STATUS: starter template, not yet applied to a live account — run
# `terraform init && terraform validate && terraform plan` and review before apply.
#
# Local component                -> AWS-native equivalent created here
# data/ticks/*.parquet           -> S3 data bucket (Parquet ticks, queried with Athena)
# backtest + C++ sweeps          -> ECS Fargate task image in ECR (AWS Batch array jobs for large sweeps)
# walk-forward folds             -> Step Functions Map state over folds (see docs/aws-native.md)
# mock/anthropic provider        -> Amazon Bedrock (IAM-scoped InvokeModel, no API keys)
# SQLite runs / promotions       -> DynamoDB promotions table + S3 Object Lock records bucket
# cost.monthly_alert_usd         -> AWS Budgets alert

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "event-backtester", owner = var.owner, data_class = "synthetic-ticks" } }
}

data "aws_caller_identity" "me" {}

locals {
  prefix = "event-backtester-${var.env}"
}

# ---------- storage (DATA-01, OBS-03)
resource "aws_s3_bucket" "data" { bucket = "${local.prefix}-data-${data.aws_caller_identity.me.account_id}" }

# Write-once records: approvals / dispositions can't be edited or deleted inside the retention period (OBS-03)
resource "aws_s3_bucket" "records" {
  bucket              = "${local.prefix}-records-${data.aws_caller_identity.me.account_id}"
  object_lock_enabled = true
}

resource "aws_s3_bucket_object_lock_configuration" "records" {
  bucket = aws_s3_bucket.records.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.log_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { data = aws_s3_bucket.data.id, records = aws_s3_bucket.records.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = { data = aws_s3_bucket.data.id, records = aws_s3_bucket.records.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_versioning" "all" {
  for_each = { data = aws_s3_bucket.data.id, records = aws_s3_bucket.records.id }
  bucket   = each.value
  versioning_configuration { status = "Enabled" }
}

# ---------- compute image
resource "aws_ecr_repository" "app" {
  name = local.prefix
  image_scanning_configuration { scan_on_push = true } # SEC-06
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.prefix}"
  retention_in_days = var.cloudwatch_retention_days # OBS-03
}

# ---------- least-privilege task role (SEC-03, SEC-05)
data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "${local.prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "ReadWriteData"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    sid       = "AppendRecordsOnly" # no Delete, no PutObjectRetention: records are write-once
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.records.arn}/*"]
  }
  statement {
    sid       = "InvokeApprovedModelsOnly" # SEC-05; Converse API calls authorize as InvokeModel
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.approved_bedrock_model_arns
  }
EXTRA_POLICY}

resource "aws_iam_role_policy" "task" {
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ---------- cost alert (COST-04)
resource "aws_budgets_budget" "ai" {
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:project$event-backtester"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---------- promotion decisions
resource "aws_dynamodb_table" "promotions" {
  name         = "${local.prefix}-promotions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  attribute {
    name = "run_id"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}

resource "aws_athena_workgroup" "wg" {
  name = local.prefix
  configuration {
    enforce_workgroup_configuration = true
    bytes_scanned_cutoff_per_query  = 10737418240 # 10 GB guardrail (COST-01)
    result_configuration { output_location = "s3://${aws_s3_bucket.data.bucket}/athena/" }
  }
}
