# Taking Lil'Helper to AWS

The household version runs on one small server at home (the EVO-X1). For a hosted version serving many households,
each piece has a direct AWS equivalent:

| Local | AWS |
|---|---|
| API (`helper serve`, FastAPI) | App Runner, or Lambda behind API Gateway (the solver finishes a week in a few seconds) |
| SQLite on the household's server | Aurora Serverless v2 (Postgres) with a household id on every row, or DynamoDB |
| Magic-link sign-in, signed sessions | Cognito user pool with email OTP; one group per household, adults only can approve |
| Saturday / Sunday / Wednesday jobs (APScheduler) | EventBridge Scheduler → Lambda, one schedule per household time zone |
| Email (Resend) | SES with a verified domain |
| Recipe ideas, notes, flyer reading (aliases) | Bedrock: a small text model for ideas and notes, a vision model for flyers, chosen by the same aliases |
| Fridge PDFs | Lambda with WeasyPrint in a container image; PDFs to S3 with a 7-day lifecycle, opened by pre-signed URL |
| Calendar feed | Same endpoint; the feed key becomes per-household and rotatable |
| Flyer photos | S3 upload by pre-signed URL, deleted after reading (1-day lifecycle) |
| Phone app builds | Expo EAS (unchanged) |
| Secrets (`HELPER_SECRET`, Instacart key) | Secrets Manager, read by the function role |
| Run log, audit | CloudWatch Logs (counts and hashes only) and the audit table in the database |

The Terraform starter in `infra/aws/` creates the parts with no running cost until used: the flyer and PDF buckets
with lifecycle rules and encryption, the scheduler role, and a function role that can only read those buckets, read
its secret and invoke approved Bedrock models. It hasn't been applied to a live account.

What changes with many households: children's data moves off the family's own server, so the hosted version would
need a privacy notice, parental consent for under-13 profiles (COPPA), per-household encryption keys and a deletion
path — reasons the household version stays at home.
