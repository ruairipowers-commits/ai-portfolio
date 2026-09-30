output "landing_bucket" { value = aws_s3_bucket.landing.bucket }
output "results_bucket" { value = aws_s3_bucket.results.bucket }
output "athena_workgroup" { value = aws_athena_workgroup.wg.name }
output "glue_database" { value = aws_glue_catalog_database.db.name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "task_role_arn" { value = aws_iam_role.task.arn }
