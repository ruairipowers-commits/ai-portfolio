# Terraform starter for Lil'Helper on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# Flyer photos (deleted after a day) and fridge PDFs (a week): encrypted, never public (DATA-03, OBS-03).
resource "aws_s3_bucket" "files" {
  bucket_prefix = "${var.name}-files-"
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  rule {
    id     = "flyers-1-day"
    status = "Enabled"
    filter { prefix = "flyers/" }
    expiration { days = 1 }
  }
  rule {
    id     = "pdfs-7-days"
    status = "Enabled"
    filter { prefix = "pdfs/" }
    expiration { days = 7 }
  }
}

# Signing secret for sessions, sign-in links and the calendar feed (SEC-01).
resource "aws_secretsmanager_secret" "app" {
  name = "${var.name}/app"
}

# The API / jobs function role: its bucket, its secret, approved models only (SEC-03, SEC-05).
resource "aws_iam_role" "fn" {
  name = "${var.name}-fn"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "fn" {
  role = aws_iam_role.fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.files.arn}/*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_secretsmanager_secret.app.arn },
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Converse"], Resource = var.approved_model_arns },
      { Effect = "Allow", Action = ["ses:SendEmail"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
    ]
  })
}

# EventBridge Scheduler may invoke the jobs function, nothing else.
resource "aws_iam_role" "scheduler" {
  name = "${var.name}-scheduler"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_cloudwatch_log_group" "fn" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}
