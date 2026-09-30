# AWS-native starter for trade-ops-exceptions.
# STATUS: starter template, not applied to a live account — run terraform init/validate/plan and review.
#
# Local                          -> AWS-native
# SQLite file                    -> RDS Postgres (private, encrypted) — same SQL, DATABASE_URL switch
# node MCP server subprocess     -> same container image (Node + Python) on ECS Fargate
# mock / Anthropic model         -> Amazon Bedrock via IAM (no API keys)
# APPROVAL_SIGNING_KEY env       -> Secrets Manager secret readable ONLY by the approval task role
# checkpoints + audit tables     -> Postgres + CloudWatch Logs with retention
# cost.monthly_alert_usd         -> AWS Budgets
#
# Separation of duties (SEC-03 / HITL-02): the investigator task role can invoke Bedrock and read the
# DB but cannot read the signing key; the approval task role can read the key but cannot invoke models.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "trade-ops-exceptions", owner = var.owner, risk_tier = "high" } }
}

locals { prefix = "tradeops-${var.env}" }

# ---------- database (private)
resource "aws_db_subnet_group" "db" {
  name       = local.prefix
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "db" {
  name   = "${local.prefix}-db"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
}

resource "aws_security_group" "tasks" {
  name   = "${local.prefix}-tasks"
  vpc_id = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "pg" {
  identifier                  = local.prefix
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  db_name                     = "tradeops"
  username                    = "tradeops"
  manage_master_user_password = true # password lives in Secrets Manager (SEC-01)
  storage_encrypted           = true
  publicly_accessible         = false
  db_subnet_group_name        = aws_db_subnet_group.db.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  backup_retention_period     = 7
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.prefix}-final"
}

# ---------- approval signing key (HITL-02)
resource "aws_secretsmanager_secret" "approval_key" {
  name        = "${local.prefix}/approval-signing-key"
  description = "HMAC key for approval tokens. Read only by the approval task role."
}

# ---------- image + logs
resource "aws_ecr_repository" "app" {
  name                 = local.prefix
  image_scanning_configuration { scan_on_push = true } # SEC-06
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.prefix}"
  retention_in_days = var.cloudwatch_retention_days # OBS-03
}

# ---------- task roles: investigator vs approver
data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "investigator" {
  name               = "${local.prefix}-investigator"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

resource "aws_iam_role_policy" "investigator" {
  role = aws_iam_role.investigator.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "InvokeApprovedModelsOnly", Effect = "Allow",
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], Resource = var.approved_bedrock_model_arns },
      { Sid = "DbCredentials", Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
        Resource = [aws_db_instance.pg.master_user_secret[0].secret_arn] },
    ]
  })
}

resource "aws_iam_role" "approver" {
  name               = "${local.prefix}-approver"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

resource "aws_iam_role_policy" "approver" {
  role = aws_iam_role.approver.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "SigningKey", Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
        Resource = [aws_secretsmanager_secret.approval_key.arn, aws_db_instance.pg.master_user_secret[0].secret_arn] },
    ]
  })
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
    values = ["user:project$trade-ops-exceptions"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
