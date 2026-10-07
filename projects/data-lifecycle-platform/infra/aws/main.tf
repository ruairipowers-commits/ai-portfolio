# AWS-native starter for data-lifecycle-platform.
# STATUS: starter template, not applied to a live account. Run
# `terraform init && terraform validate && terraform plan` and review before any apply.
#
# Local component                  -> AWS-native equivalent created here
# data/landing (fixture / Hub)     -> S3 landing bucket (encrypted, versioned, private)
# DuckDB + dbt + MetricFlow        -> Glue Data Catalog + Athena workgroup (dbt-athena; MetricFlow runs in the task)
# Oxigraph on disk                 -> Amazon Neptune (SPARQL) cluster in private subnets
# SQLite operational store         -> RDS Postgres (DLP_DATABASE_URL), credentials in Secrets Manager
# Dagster / CLI                    -> ECS Fargate task image in ECR, EventBridge schedule (or Dagster on ECS)
# mock / Anthropic provider        -> Amazon Bedrock (IAM-scoped InvokeModel, no API keys)
# AICall run log                   -> CloudWatch Logs (retention) + S3 results bucket
# cost.monthly_alert_usd           -> AWS Budgets alert
# entitlements (licensing.py)      -> unchanged in code; Lake Formation tags as a second line (documented, not built)

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "data-lifecycle-platform", owner = var.owner } }
}

data "aws_caller_identity" "me" {}

locals {
  prefix = "dlp-${var.env}"
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

resource "aws_s3_bucket_versioning" "all" {
  for_each = { landing = aws_s3_bucket.landing.id, results = aws_s3_bucket.results.id }
  bucket   = each.value
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

# ---------- semantic layer: Glue + Athena (dbt-athena target)
resource "aws_glue_catalog_database" "db" { name = replace("${local.prefix}_semantic", "-", "_") }

resource "aws_athena_workgroup" "wg" {
  name = "${local.prefix}-wg"
  configuration {
    enforce_workgroup_configuration = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/athena/"
      encryption_configuration { encryption_option = "SSE_KMS" }
    }
    bytes_scanned_cutoff_per_query = 10737418240 # 10 GB guard (COST-01 for SQL)
  }
}

# ---------- network for Neptune and RDS (private only)
resource "aws_vpc" "main" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_hostnames = true
}
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone = data.aws_availability_zones.az.names[count.index]
}
data "aws_availability_zones" "az" { state = "available" }

resource "aws_security_group" "task" {
  name   = "${local.prefix}-task"
  vpc_id = aws_vpc.main.id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]   # Bedrock/S3 via VPC endpoints in production
  }
}
resource "aws_security_group" "data" {
  name   = "${local.prefix}-data"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 8182
    to_port         = 8182
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }
}

# ---------- knowledge graph: Neptune (SPARQL endpoint replaces Oxigraph)
resource "aws_neptune_subnet_group" "g" {
  name       = "${local.prefix}-neptune"
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_neptune_cluster" "graph" {
  cluster_identifier                  = "${local.prefix}-graph"
  engine                              = "neptune"
  neptune_subnet_group_name           = aws_neptune_subnet_group.g.name
  vpc_security_group_ids              = [aws_security_group.data.id]
  iam_database_authentication_enabled = true
  storage_encrypted                   = true
  skip_final_snapshot                 = var.env != "prod"
  serverless_v2_scaling_configuration {
    min_capacity = 1
    max_capacity = 4
  }
}
resource "aws_neptune_cluster_instance" "graph" {
  cluster_identifier = aws_neptune_cluster.graph.id
  instance_class     = "db.serverless"
}

# ---------- operational store: RDS Postgres
resource "aws_db_subnet_group" "g" {
  name       = "${local.prefix}-pg"
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_db_instance" "catalog" {
  identifier                  = "${local.prefix}-catalog"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_encrypted           = true
  db_name                     = "dlp"
  username                    = "dlp"
  manage_master_user_password = true # Secrets Manager (SEC-01)
  db_subnet_group_name        = aws_db_subnet_group.g.name
  vpc_security_group_ids      = [aws_security_group.data.id]
  backup_retention_period     = 14
  skip_final_snapshot         = var.env != "prod"
}

# ---------- compute: one container for build, API and app
resource "aws_ecr_repository" "app" {
  name = local.prefix
  image_scanning_configuration { scan_on_push = true } # SEC-06
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/dlp/${var.env}"
  retention_in_days = var.cloudwatch_retention_days
}

resource "aws_iam_role" "task" {
  name = "${local.prefix}-task"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [aws_s3_bucket.landing.arn, "${aws_s3_bucket.landing.arn}/*"] },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"], Resource = [aws_s3_bucket.results.arn, "${aws_s3_bucket.results.arn}/*"] },
      { Effect = "Allow", Action = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"], Resource = aws_athena_workgroup.wg.arn },
      { Effect = "Allow", Action = ["glue:Get*", "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"], Resource = "*" },
      # SEC-03 / SEC-05: only the approved models in config/models.yaml
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Converse"], Resource = var.approved_bedrock_model_arns },
      { Effect = "Allow", Action = ["neptune-db:ReadDataViaQuery", "neptune-db:WriteDataViaQuery", "neptune-db:DeleteDataViaQuery"], Resource = "${aws_neptune_cluster.graph.arn}/*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_db_instance.catalog.master_user_secret[0].secret_arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.app.arn}:*" },
    ]
  })
}

# ---------- cost (COST-04)
resource "aws_budgets_budget" "monthly" {
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:project$data-lifecycle-platform"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
