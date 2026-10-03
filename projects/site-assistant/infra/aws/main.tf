# Terraform starter for site-assistant on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "region" { default = "us-east-1" }
variable "name" { default = "site-assistant" }

provider "aws" { region = var.region }

# Activity log: searches, questions and page views; items expire after the retention period (OBS-03).
resource "aws_dynamodb_table" "activity" {
  name         = "${var.name}-activity"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "day"
  range_key    = "id"
  attribute {
    name = "day"
    type = "S"
  }
  attribute {
    name = "id"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
}

# SMTP, Cloudflare and GitHub tokens (SEC-01). Values are set outside Terraform.
resource "aws_secretsmanager_secret" "tokens" {
  name = "${var.name}/tokens"
}

# The daily engagement email: EventBridge Scheduler calls the digest function at 07:00 New York time.
resource "aws_iam_role" "scheduler" {
  name = "${var.name}-scheduler"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

output "activity_table" { value = aws_dynamodb_table.activity.name }
output "tokens_secret" { value = aws_secretsmanager_secret.tokens.arn }
