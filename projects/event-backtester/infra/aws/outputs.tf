output "data_bucket" { value = aws_s3_bucket.data.bucket }
output "records_bucket" { value = aws_s3_bucket.records.bucket }
output "promotions_table" { value = aws_dynamodb_table.promotions.name }
output "athena_workgroup" { value = aws_athena_workgroup.wg.name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "task_role_arn" { value = aws_iam_role.task.arn }
