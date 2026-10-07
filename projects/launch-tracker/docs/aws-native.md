# Taking launch-tracker to AWS

| Local | AWS |
|---|---|
| Streamlit app | App Runner or ECS Fargate behind CloudFront |
| Refresh loop / Prefect flows | EventBridge Scheduler → Lambda: hourly upcoming refresh (within Launch Library 2's budget), daily GCAT and SATCAT |
| `ll2_requests` budget table | The same table in the database, or a DynamoDB counter with a one-hour TTL per request |
| DuckDB file | Parquet in S3 (one prefix per table, rewritten per refresh) queried by Athena; or keep DuckDB in the task and the file in S3 |
| Raw source files (cache) | S3, versioned, so any day's data can be rebuilt |
| Summaries | Bedrock (a small model is enough), chosen by the same aliases |
| Audit tables | CloudWatch Logs with retention, plus the audit tables in S3 |
| Images | Linked, never copied: only licensed images are shown, from their source URLs |
| Keys in `.env` | None for models (Bedrock through the role); the optional LL2 key in Secrets Manager |

The Terraform starter in `infra/aws/` creates the parts with no running cost until used: a versioned, encrypted,
private bucket for raw files and tables, an hourly EventBridge schedule, a refresh function role that can only write
that bucket and read the one secret, and a summary role that can only invoke approved Bedrock models. It hasn't been
applied to a live account (and `terraform` isn't installed in the build sandbox, so it hasn't been validated either).
