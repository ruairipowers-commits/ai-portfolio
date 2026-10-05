output "topics_table" { value = aws_dynamodb_table.topics.name }
output "link_secret_arn" { value = aws_secretsmanager_secret.link_secret.arn }
