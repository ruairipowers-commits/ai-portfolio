output "answer_key_kms_arn" { value = aws_kms_key.answer_key.arn }
output "sandbox_subnet_id" { value = aws_subnet.sandbox.id }
output "sandbox_security_group_id" { value = aws_security_group.sandbox.id }
output "assets_bucket" { value = aws_s3_bucket.assets.bucket }
