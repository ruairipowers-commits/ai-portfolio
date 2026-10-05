variable "name" {
  type    = string
  default = "editorial-agents"
}
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "classifier_model_id" {
  type        = string
  description = "Bedrock model for the classifier alias (a small, cheap model)"
}
variable "from_address" {
  type        = string
  description = "Verified SES sender for the owner's topic email"
}
variable "scout_lambda_arn" {
  type        = string
  description = "The packaged scout function (editorial.scout.run behind a Lambda handler)"
}
variable "scheduler_role_arn" {
  type = string
}
