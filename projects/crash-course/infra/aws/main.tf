# Terraform starter for crash-course on AWS (see docs/aws-native.md). Not applied to a live account.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# Course content: every level version as YAML. Versioned, encrypted, never public; published versions are locked so a
# level learners passed can always be shown exactly as it was (DATA-01, OBS-03).
resource "aws_s3_bucket" "content" {
  bucket_prefix       = "${var.name}-content-"
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "content" {
  bucket = aws_s3_bucket.content.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "content" {
  bucket = aws_s3_bucket.content.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.published_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "content" {
  bucket                  = aws_s3_bucket.content.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "content" {
  bucket = aws_s3_bucket.content.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

# Build and revision jobs: drafts run in the background, never in a web request. Failed jobs land in a DLQ.
resource "aws_sqs_queue" "jobs_dlq" {
  name                      = "${var.name}-jobs-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name}-jobs"
  visibility_timeout_seconds = 900
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 2
  })
}

# Signing secret for sessions, sign-in links and owner approval links (SEC-01).
resource "aws_secretsmanager_secret" "app" {
  name = "${var.name}/app"
}

resource "aws_cloudwatch_log_group" "service" {
  name              = "/${var.name}/service"
  retention_in_days = var.log_retention_days
}

# The service's role: only this bucket, this queue, this secret, this email identity, the approved models.
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com", "lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "service" {
  name               = "${var.name}-service"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "service" {
  statement {
    sid       = "Content"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.content.arn, "${aws_s3_bucket.content.arn}/*"]
  }
  statement {
    sid       = "Jobs"
    actions   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.jobs.arn]
  }
  statement {
    sid       = "Secret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    sid       = "Email"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [var.ses_identity_arn]
  }
  statement {
    sid       = "ApprovedModelsOnly"
    actions   = ["bedrock:InvokeModel", "bedrock:Converse"]
    resources = var.approved_model_arns
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.service.arn}:*"]
  }
}

resource "aws_iam_role_policy" "service" {
  role   = aws_iam_role.service.id
  policy = data.aws_iam_policy_document.service.json
}
