# Taking speaking-coach to AWS

| Local | AWS |
|---|---|
| Streamlit app | App Runner or ECS Fargate behind CloudFront (or a small static front end + API Gateway) |
| Pipeline (`workflow.analyze`) | Lambda: detection and scoring are pure Python and finish in well under a second for a talk-length transcript |
| Uploads in memory | S3 bucket with a 1-day lifecycle rule and SSE-KMS; the function reads, analyses and deletes |
| Disambiguator and coach models | Bedrock (a small model for the disambiguator, a stronger one for the coach), chosen by the same aliases |
| Pseudonymization (`privacy.py`) | Same code, or Amazon Comprehend `DetectPiiEntities` for names in more languages |
| Opt-in history (SQLite) | DynamoDB keyed by user, numbers only, TTL for retention |
| Run log (`logs/runs.jsonl`) | CloudWatch Logs with a retention policy; still hashes and counts only |
| Audio (not in v1) | Amazon Transcribe with filler words kept (it drops them only if you ask for that) |
| Keys in `.env` | None needed: Bedrock through the function's IAM role |

The Terraform starter in `infra/aws/` creates the parts with no running cost until used: the upload bucket with
its lifecycle and encryption, the history table with TTL, and a function role that can only read that bucket,
write that table and invoke approved Bedrock models. It hasn't been applied to a live account.
