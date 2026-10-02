output "landing_bucket" { value = aws_s3_bucket.landing.bucket }
output "mwaa_bucket" { value = aws_s3_bucket.mwaa.bucket }
output "archive_bucket" { value = aws_s3_bucket.archive.bucket }
output "db_endpoint" { value = aws_db_instance.eod.endpoint }
output "db_secret_arn" { value = aws_db_instance.eod.master_user_secret[0].secret_arn }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
output "mwaa_webserver_url" { value = aws_mwaa_environment.eod.webserver_url }
