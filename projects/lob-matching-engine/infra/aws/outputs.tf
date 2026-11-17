output "data_bucket" { value = aws_s3_bucket.data.bucket }
output "records_bucket" { value = aws_s3_bucket.records.bucket }
output "orders_stream" { value = aws_kinesis_stream.orders.name }
output "alerts_table" { value = aws_dynamodb_table.alerts.name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "task_role_arn" { value = aws_iam_role.task.arn }
