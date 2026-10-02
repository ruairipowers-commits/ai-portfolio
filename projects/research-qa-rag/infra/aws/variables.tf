variable "region" {
  type    = string
  default = "us-east-1"
}
variable "env" {
  type    = string
  default = "dev"
}
variable "owner" {
  type        = string
  description = "Accountable owner (HITL-04)"
}
variable "alert_email" { type = string }
variable "monthly_budget_usd" {
  type    = number
  default = 50
}
variable "embedding_model_arn" {
  type        = string
  description = "Embedding model for the knowledge base, e.g. Titan Text Embeddings v2 (keep in sync with embed-primary)"
}
variable "approved_bedrock_model_arns" {
  type        = list(string)
  description = "Answer-model ARNs the API may invoke (keep in sync with config/models.yaml)"
}
variable "vector_index_name" {
  type    = string
  default = "research-index"
}
variable "chunk_max_tokens" {
  type    = number
  default = 300
}
variable "chunk_overlap_pct" {
  type    = number
  default = 20
}
variable "cloudwatch_retention_days" {
  type    = number
  default = 2557
}
