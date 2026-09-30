output "db_endpoint" { value = aws_db_instance.pg.address }
output "db_secret_arn" { value = aws_db_instance.pg.master_user_secret[0].secret_arn }
output "approval_key_secret_arn" { value = aws_secretsmanager_secret.approval_key.arn }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "investigator_role_arn" { value = aws_iam_role.investigator.arn }
output "approver_role_arn" { value = aws_iam_role.approver.arn }
