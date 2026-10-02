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
variable "oncall_email" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" {
  type        = list(string)
  description = "At least two private subnets in different AZs (MWAA requirement)"
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "airflow_version" {
  type        = string
  default     = "2.10.3"
  description = "Use the newest version MWAA offers; the DAG imports work on Airflow 2.x and 3.x"
}
variable "approved_bedrock_model_arns" {
  type        = list(string)
  description = "Explainer model ARNs (keep in sync with config/models.yaml)"
}
variable "monthly_budget_usd" {
  type    = number
  default = 40
}
variable "log_retention_days" {
  type    = number
  default = 2555
}
