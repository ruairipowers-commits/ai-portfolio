# AWS-native starter for altdata-triage.
# STATUS: starter template, not yet applied to a live account — run
# `terraform init && terraform validate && terraform plan` and review before apply.
#
# Local component          -> AWS-native equivalent created here
# data/incoming/ folder    -> S3 landing bucket (encrypted, versioned, private)
# DuckDB + dbt-duckdb      -> Glue Data Catalog + Athena workgroup (dbt-athena)
# mock/anthropic provider  -> Amazon Bedrock (IAM-scoped InvokeModel, no API keys)
# local CLI run            -> ECS Fargate task image in ECR (schedule via EventBridge)
# audit.* DuckDB tables    -> CloudWatch Logs (retention) + S3 results bucket
# cost.monthly_alert_usd   -> AWS Budgets alert

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "altdata-triage", owner = var.owner, data_class = "vendor-sample" } }
}

data "aws_caller_identity" "me" {}

locals {
  prefix = "altdata-triage-${var.env}"
}

# ---------- storage (DATA-01, OBS-03)
resource "aws_s3_bucket" "landing" { bucket = "${local.prefix}-landing-${data.aws_caller_identity.me.account_id}" }
resource "aws_s3_bucket" "results" { bucket = "${local.prefix}-results-${data.aws_caller_identity.me.account_id}" }

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { landing = aws_s3_bucket.landing.id, results = aws_s3_bucket.results.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = { landing = aws_s3_bucket.landing.id, results = aws_s3_bucket.results.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_versioning" "results" {
  bucket = aws_s3_bucket.results.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id
  rule {
    id     = "retention"
    status = "Enabled"
    filter {}
    expiration { days = var.log_retention_days }
  }
}

# ---------- warehouse (dbt-athena target in dbt/profiles.yml)
resource "aws_glue_catalog_database" "db" { name = replace(local.prefix, "-", "_") }

resource "aws_athena_workgroup" "wg" {
  name = local.prefix
  configuration {
    enforce_workgroup_configuration = true
    bytes_scanned_cutoff_per_query  = 10737418240 # 10 GB guardrail (COST-01)
    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/athena/"
    }
  }
}

# ---------- compute image
resource "aws_ecr_repository" "app" {
  name                 = local.prefix
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
    sid       = "ReadLanding"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.landing.arn, "${aws_s3_bucket.landing.arn}/*"]
  }
  statement {
    sid       = "WriteResults"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.results.arn, "${aws_s3_bucket.results.arn}/*"]
  }
  statement {
    sid       = "Athena"
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "glue:Get*", "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"]
    resources = ["*"]
  }
  statement {
    sid       = "InvokeApprovedModelsOnly" # SEC-05; Converse API calls authorize as InvokeModel
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.approved_bedrock_model_arns
  }
}

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
    values = ["user:project$altdata-triage"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
