variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "crash-course"
}

variable "approved_model_arns" {
  description = "Bedrock model or inference-profile ARNs the service may call (SEC-05): a small moderator, a writer"
  type        = list(string)
}

variable "ses_identity_arn" {
  description = "Verified SES identity (domain) the service may send sign-in and approval email from"
  type        = string
}

variable "published_retention_days" {
  description = "Object Lock retention on published course versions (governance mode, so an admin can still correct one)"
  type        = number
  default     = 365
}

variable "log_retention_days" {
  description = "OBS-03: the run log holds counts and hashes only"
  type        = number
  default     = 365
}
