variable "region" {
  type    = string
  default = "us-east-1"
}
variable "env" {
  type    = string
  default = "prod"
}
variable "owner" {
  type        = string
  description = "Accountable owner (HITL-04), e.g. the CRO's office"
}
variable "alert_email" { type = string }
variable "image_uri" {
  type        = string
  description = "ECR image URI of the console (docker build -t … . && docker push …)"
}
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "retention_days" {
  type    = number
  default = 2555 # ~7 years (OBS-03)
}
variable "monthly_budget_usd" {
  type    = number
  default = 50
}
