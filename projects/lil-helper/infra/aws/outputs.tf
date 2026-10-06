output "files_bucket" { value = aws_s3_bucket.files.bucket }
output "app_secret_arn" { value = aws_secretsmanager_secret.app.arn }
output "function_role_arn" { value = aws_iam_role.fn.arn }
output "scheduler_role_arn" { value = aws_iam_role.scheduler.arn }
