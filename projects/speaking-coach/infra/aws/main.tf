# Terraform starter for speaking-coach on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# Uploads live for one day at most (DATA-03, OBS-03); encrypted; never public.
resource "aws_s3_bucket" "uploads" {
  bucket_prefix = "${var.name}-uploads-"
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    id     = "delete-after-a-day"
    status = "Enabled"
    filter {}
    expiration { days = 1 }
  }
}

# Opt-in progress history: numbers only, expires after the retention period.
resource "aws_dynamodb_table" "history" {
  name         = "${var.name}-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user"
  range_key    = "ts"
  attribute {
    name = "user"
    type = "S"
  }
  attribute {
    name = "ts"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# The analysis function's role: read uploads, write history, invoke only the approved models (SEC-03, SEC-05).
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
      { Effect = "Allow", Action = ["s3:GetObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.uploads.arn}/*" },
      { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:Query"], Resource = aws_dynamodb_table.history.arn },
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Converse"], Resource = var.approved_model_arns },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
    ]
  })
}

resource "aws_cloudwatch_log_group" "fn" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}
