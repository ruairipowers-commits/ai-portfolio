output "uploads_bucket" { value = aws_s3_bucket.uploads.bucket }
output "history_table" { value = aws_dynamodb_table.history.name }
output "function_role_arn" { value = aws_iam_role.fn.arn }
