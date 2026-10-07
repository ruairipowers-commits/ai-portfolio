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
  default = 150
}
variable "approved_bedrock_model_arns" {
  type        = list(string)
  description = "Foundation-model / inference-profile ARNs the task may invoke (keep in sync with config/models.yaml)"
}
variable "log_retention_days" {
  type    = number
  default = 2555
}
variable "cloudwatch_retention_days" {
  type    = number
  default = 2557 # nearest CloudWatch-supported value to ~7 years
}
