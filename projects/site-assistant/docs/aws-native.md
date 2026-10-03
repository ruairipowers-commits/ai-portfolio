# Taking site-assistant to AWS

| Local (home server) | AWS |
|---|---|
| FastAPI container | Lambda (with a response-streaming function URL) or ECS Fargate behind CloudFront |
| Ollama local model | Bedrock: an open-weight model (Llama, Mistral) or a Claude model, chosen by the same `chat` alias |
| SQLite FTS5 over the blog index | Bedrock Knowledge Bases over the site (web crawler connector), or OpenSearch Serverless |
| Activity log in SQLite | DynamoDB with a TTL for retention, or CloudWatch Logs |
| Daily digest thread | EventBridge Scheduler → Lambda, email through SES |
| Tokens in `.env` | Secrets Manager |
| Per-visitor limits | AWS WAF rate-based rules in front of CloudFront |

The Terraform starter in `infra/aws/` creates the parts with no running cost until used: the secrets, a
DynamoDB table with TTL and the schedule. It hasn't been applied to a live account.
