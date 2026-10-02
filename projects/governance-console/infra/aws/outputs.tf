output "console_url" { value = "https://${aws_apprunner_service.console.service_url}" }
output "ingest_token_secret_arn" { value = aws_secretsmanager_secret.ingest.arn }
output "admin_token_secret_arn" { value = aws_secretsmanager_secret.admin.arn }
output "events_archive_bucket" { value = aws_s3_bucket.archive.bucket }
