variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "launch-tracker"
}

variable "approved_model_arns" {
  description = "Bedrock model or inference-profile ARNs the summary role may call (SEC-05)"
  type        = list(string)
}

variable "refresh_minutes" {
  description = "Upcoming-launch refresh cadence; 60 keeps one refresh inside Launch Library 2's free tier"
  type        = number
  default     = 60
}

variable "log_retention_days" {
  description = "OBS-03"
  type        = number
  default     = 365
}
