output "docs_bucket" { value = aws_s3_bucket.docs.bucket }
output "knowledge_base_id" { value = aws_bedrockagent_knowledge_base.research.id }
output "data_source_id" { value = aws_bedrockagent_data_source.docs.data_source_id }
output "collection_endpoint" { value = aws_opensearchserverless_collection.kb.collection_endpoint }
output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }
output "api_task_role_arn" { value = aws_iam_role.api.arn }
