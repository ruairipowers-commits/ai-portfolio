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
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "monthly_budget_usd" {
  type    = number
  default = 50
}
variable "approved_bedrock_model_arns" {
  type        = list(string)
  description = "Model / inference-profile ARNs the investigator may invoke (keep in sync with config/models.yaml)"
}
variable "cloudwatch_retention_days" {
  type    = number
  default = 2557
}
