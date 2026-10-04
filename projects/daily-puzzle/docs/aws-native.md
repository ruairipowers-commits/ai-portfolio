# Taking daily-puzzle to AWS

| Local (home server) | AWS |
|---|---|
| APScheduler `tick()` every minute | EventBridge Scheduler → Lambda running `tick()` (same idempotent function) |
| FastAPI player site | Lambda behind API Gateway (Mangum), or App Runner; CloudFront in front |
| Generator / solver via Ollama or a provider | Bedrock (Converse), one model per alias; IAM-scoped, no keys |
| Sandbox subprocess | One ECS Fargate task per run: no task role, no internet, a VPC endpoint to an S3 mirror of allow-listed model files, read-only root filesystem |
| SQLite | Aurora Serverless v2 Postgres (same SQLAlchemy tables) or DynamoDB |
| Encrypted answer key (Fernet + env secret) | KMS: encrypt with a key the site role can't decrypt; only the reveal Lambda can |
| Resend | SES with configuration-set suppression, List-Unsubscribe headers |
| Secrets in `.env` | Secrets Manager |
| Rate limits in memory | AWS WAF rate-based rules |
| Puzzle-pack PDFs | Lambda container image with WeasyPrint; PDFs in S3 with pre-signed links |

The KMS split is the main improvement over the home-server version: the role serving players could not read an
answer before close even if compromised. The Terraform starter in `infra/aws/` creates the KMS key, the secrets,
the scheduler and the sandbox task's network isolation. It hasn't been applied to a live account.
