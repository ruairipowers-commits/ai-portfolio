# Terraform starter for launch-tracker on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# Raw source files and the tables built from them: private, encrypted, versioned (DATA-01: any day can be rebuilt).
resource "aws_s3_bucket" "data" {
  bucket_prefix = "${var.name}-data-"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

# Optional Launch Library 2 key (SEC-01). The value is set outside Terraform.
resource "aws_secretsmanager_secret" "ll2" {
  name = "${var.name}/ll2-api-key"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# The refresh function may write the bucket and read the one secret — nothing else (SEC-03).
resource "aws_iam_role" "refresh" {
  name               = "${var.name}-refresh"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "refresh" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.ll2.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.refresh.arn}:*"]
  }
}

resource "aws_iam_role_policy" "refresh" {
  role   = aws_iam_role.refresh.id
  policy = data.aws_iam_policy_document.refresh.json
}

# The summary role may read the bucket and invoke approved models only (SEC-05).
resource "aws_iam_role" "summary" {
  name               = "${var.name}-summary"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "summary" {
  statement {
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:Converse"]
    resources = var.approved_model_arns
  }
}

resource "aws_iam_role_policy" "summary" {
  role   = aws_iam_role.summary.id
  policy = data.aws_iam_policy_document.summary.json
}

resource "aws_cloudwatch_log_group" "refresh" {
  name              = "/aws/lambda/${var.name}-refresh"
  retention_in_days = var.log_retention_days
}

# Hourly schedule for the refresh function (the function itself is deployed from the same code as `launches fetch`).
data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_scheduler_schedule" "refresh" {
  name                = "${var.name}-refresh"
  schedule_expression = "rate(${var.refresh_minutes} minutes)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = "arn:aws:lambda:${var.region}:${data.aws_caller_identity.me.account_id}:function:${var.name}-refresh"
    role_arn = aws_iam_role.scheduler.arn
  }
}

data "aws_caller_identity" "me" {}
