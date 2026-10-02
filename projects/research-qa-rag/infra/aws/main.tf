# AWS-native starter for research-qa-rag.
# STATUS: starter template, not yet applied to a live account — run
# `terraform init && terraform validate && terraform plan` and review before apply.
#
# Local component                  -> AWS-native equivalent created here
# data/corpus/ + manifest.yaml     -> S3 documents bucket; one <file>.metadata.json sidecar per document
#                                     carrying entitlement / licence (Bedrock KB metadata filtering)
# SQLite FTS5 + sqlite-vec         -> Bedrock Knowledge Base on OpenSearch Serverless (hybrid search)
# mock-hash-384 embeddings         -> Titan Text Embeddings v2 (set in the knowledge base)
# answer model alias               -> Bedrock InvokeModel / Converse, IAM-scoped to approved ARNs
# FastAPI container                -> ECR image run on ECS Fargate or App Runner (task role below)
# cost.monthly_alert_usd           -> AWS Budgets alert
#
# One manual step: the vector index inside the OpenSearch collection must exist before the knowledge base is
# created (the AWS provider can't create it). Create it with the opensearch provider or the console — see
# docs/aws-native.md.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "research-qa-rag", owner = var.owner, data_class = "research-licensed" } }
}

data "aws_caller_identity" "me" {}

locals {
  prefix     = "rqa-${var.env}"
  collection = "${local.prefix}-kb"
}

# ---------- documents (DATA-01, DATA-04 via metadata sidecars)
resource "aws_s3_bucket" "docs" { bucket = "${local.prefix}-docs-${data.aws_caller_identity.me.account_id}" }

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_versioning" "docs" {
  bucket = aws_s3_bucket.docs.id
  versioning_configuration { status = "Enabled" } # DATA-05: every document version is kept
}

# ---------- OpenSearch Serverless vector collection
resource "aws_opensearchserverless_security_policy" "enc" {
  name   = "${local.collection}-enc"
  type   = "encryption"
  policy = jsonencode({ Rules = [{ ResourceType = "collection", Resource = ["collection/${local.collection}"] }], AWSOwnedKey = true })
}

resource "aws_opensearchserverless_security_policy" "net" {
  name = "${local.collection}-net"
  type = "network"
  # Public endpoint for the starter; use a VPC endpoint (SourceVPCEs) in production.
  policy = jsonencode([{ Rules = [{ ResourceType = "collection", Resource = ["collection/${local.collection}"] }], AllowFromPublic = true }])
}

resource "aws_opensearchserverless_collection" "kb" {
  name       = local.collection
  type       = "VECTORSEARCH"
  depends_on = [aws_opensearchserverless_security_policy.enc, aws_opensearchserverless_security_policy.net]
}

resource "aws_opensearchserverless_access_policy" "kb" {
  name = "${local.collection}-access"
  type = "data"
  policy = jsonencode([{
    Rules = [
      { ResourceType = "index", Resource = ["index/${local.collection}/*"], Permission = ["aoss:*"] },
      { ResourceType = "collection", Resource = ["collection/${local.collection}"], Permission = ["aoss:*"] }
    ]
    Principal = [aws_iam_role.kb.arn, data.aws_caller_identity.me.arn]
  }])
}

# ---------- Bedrock knowledge base (least privilege: read docs bucket, embed with one model, write one collection)
resource "aws_iam_role" "kb" {
  name = "${local.prefix}-kb"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "bedrock.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "kb" {
  role = aws_iam_role.kb.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [aws_s3_bucket.docs.arn, "${aws_s3_bucket.docs.arn}/*"] },
      { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = [var.embedding_model_arn] },
      { Effect = "Allow", Action = ["aoss:APIAccessAll"], Resource = [aws_opensearchserverless_collection.kb.arn] }
    ]
  })
}

resource "aws_bedrockagent_knowledge_base" "research" {
  name     = "${local.prefix}-research"
  role_arn = aws_iam_role.kb.arn
  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration { embedding_model_arn = var.embedding_model_arn }
  }
  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.kb.arn
      vector_index_name = var.vector_index_name
      field_mapping {
        vector_field   = "embedding"
        text_field     = "text"
        metadata_field = "metadata"
      }
    }
  }
  depends_on = [aws_opensearchserverless_access_policy.kb]
}

resource "aws_bedrockagent_data_source" "docs" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.research.id
  name              = "documents"
  data_source_configuration {
    type = "S3"
    s3_configuration { bucket_arn = aws_s3_bucket.docs.arn }
  }
  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = var.chunk_max_tokens   # ~ingest.chunk_words in config/settings.yaml
        overlap_percentage = var.chunk_overlap_pct
      }
    }
  }
}

# ---------- API task role: retrieve from this KB, invoke approved answer models only
resource "aws_ecr_repository" "api" {
  name                 = "${local.prefix}-api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true } # SEC-06
}

resource "aws_iam_role" "api" {
  name = "${local.prefix}-api"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["bedrock:Retrieve"], Resource = [aws_bedrockagent_knowledge_base.research.arn] },
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Converse"], Resource = var.approved_bedrock_model_arns }
    ]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/rqa/${var.env}/api"
  retention_in_days = var.cloudwatch_retention_days # OBS-03
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
    values = ["user:project$research-qa-rag"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
