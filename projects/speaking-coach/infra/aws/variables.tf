variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "speaking-coach"
}

variable "approved_model_arns" {
  description = "Bedrock model or inference-profile ARNs the function may call (SEC-05)"
  type        = list(string)
}

variable "log_retention_days" {
  description = "OBS-03: the run log holds counts and hashes only"
  type        = number
  default     = 90
}
