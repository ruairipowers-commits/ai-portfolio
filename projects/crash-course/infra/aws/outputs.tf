output "content_bucket" { value = aws_s3_bucket.content.bucket }
output "jobs_queue_url" { value = aws_sqs_queue.jobs.url }
output "app_secret_arn" { value = aws_secretsmanager_secret.app.arn }
output "service_role_arn" { value = aws_iam_role.service.arn }
