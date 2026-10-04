variable "region" { default = "us-east-1" }
variable "name" { default = "daily-puzzle" }
variable "suffix" { description = "makes the bucket name unique" }
variable "tick_function_arn" { description = "Lambda running daily_puzzle.cycle.tick" }
variable "bedrock_model_arns" { type = list(string) }
variable "monthly_budget_usd" { default = "5" }
variable "alert_email" {}
