# Terraform starter for daily-puzzle on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# --- the answer key: only the reveal function may decrypt (SEC-04, NFR-3) --------------------------
resource "aws_kms_key" "answer_key" {
  description         = "${var.name}: encrypts puzzle answer keys until submissions close"
  enable_key_rotation = true
}

resource "aws_iam_role" "reveal" {
  name               = "${var.name}-reveal"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "site" {                       # serves players: may encrypt, never decrypt
  name               = "${var.name}-site"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "reveal_decrypt" {
  role = aws_iam_role.reveal.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.answer_key.arn }] })
}

resource "aws_iam_role_policy" "site_encrypt_only" {
  role = aws_iam_role.site.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["kms:Encrypt"], Resource = aws_kms_key.answer_key.arn },
    { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Converse"], Resource = var.bedrock_model_arns }] })
}

# --- secrets (SEC-01): HMAC salt, admin token, email provider ---------------------------------------
resource "aws_secretsmanager_secret" "app" {
  name = "${var.name}/app"
}

# --- the scheduler: tick() every minute -------------------------------------------------------------
resource "aws_iam_role" "scheduler" {
  name = "${var.name}-scheduler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "scheduler.amazonaws.com" } }] })
}

resource "aws_scheduler_schedule" "tick" {
  name                = "${var.name}-tick"
  schedule_expression = "rate(1 minute)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = var.tick_function_arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

# --- the sandbox: Fargate tasks with no role and no route to the internet (SEC-03) -----------------
resource "aws_vpc" "sandbox" {
  cidr_block           = "10.42.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.name}-sandbox" }
}

resource "aws_subnet" "sandbox" {
  vpc_id     = aws_vpc.sandbox.id
  cidr_block = "10.42.0.0/25"
}

resource "aws_security_group" "sandbox" {               # no ingress; egress only to the S3 gateway endpoint
  name   = "${var.name}-sandbox"
  vpc_id = aws_vpc.sandbox.id
  egress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.s3.prefix_list_id]
  }
}

resource "aws_vpc_endpoint" "s3" {                      # allow-listed model files are mirrored to S3
  vpc_id       = aws_vpc.sandbox.id
  service_name = "com.amazonaws.${var.region}.s3"
}

resource "aws_s3_bucket" "assets" {
  bucket = "${var.name}-allowed-assets-${var.suffix}"
}

resource "aws_ecs_cluster" "sandbox" {
  name = "${var.name}-sandbox"
}

resource "aws_budgets_budget" "monthly" {               # COST-04
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
