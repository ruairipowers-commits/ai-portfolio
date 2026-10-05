# Terraform starter for editorial-agents on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# --- the topic queue, owner actions and runs (OBS-01) ------------------------------------------------
resource "aws_dynamodb_table" "topics" {
  name         = "${var.name}-topics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
}

# --- the link-signing secret (SEC-01) ----------------------------------------------------------------
resource "aws_secretsmanager_secret" "link_secret" {
  name = "${var.name}/link-secret"
}

# --- the scout: a scheduled Lambda that may only read its secret and write its table (SEC-03) --------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scout" {
  name               = "${var.name}-scout"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "scout" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.topics.arn]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.link_secret.arn]
  }
  statement {
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${var.region}::foundation-model/${var.classifier_model_id}"]
  }
  statement {
    actions   = ["ses:SendEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.from_address]
    }
  }
}

resource "aws_iam_role_policy" "scout" {
  role   = aws_iam_role.scout.id
  policy = data.aws_iam_policy_document.scout.json
}

resource "aws_scheduler_schedule" "scout" {
  name                         = "${var.name}-scout-daily"
  schedule_expression          = "cron(40 9 * * ? *)" # 05:40 New York (EDT); adjust for EST
  flexible_time_window { mode = "OFF" }
  target {
    arn      = var.scout_lambda_arn
    role_arn = var.scheduler_role_arn
  }
}
