# Taking crash-course to AWS

The live version runs as one container on the EVO-X1 with a data volume. For a firm running it as an internal
learning platform, each piece has a direct AWS equivalent:

| Local | AWS |
|---|---|
| Learner site + owner page (`course serve`, FastAPI) | App Runner, or ECS Fargate behind an ALB (App Runner is closed to new customers) |
| SQLite (learners, attempts, feedback, approvals, jobs) | Aurora Serverless v2 (Postgres); the SQL is portable |
| Course YAML (bundled in git; runtime versions on the volume) | S3 with versioning and Object Lock on published versions, so a published level can't be silently changed |
| Magic-link sign-in | Cognito user pool with email one-time codes, or the firm's SSO (SAML / OIDC) |
| Jobs table + worker thread | SQS queue → Lambda (moderation, revisions) and a Fargate task for long drafts |
| Email (Resend) | SES with a verified domain |
| Moderator, writer, reviser (aliases) | Bedrock: a small model for moderation, a stronger one for writing, chosen by the same aliases; Bedrock Guardrails as a second moderation layer |
| `COURSE_SECRET`, model keys | Secrets Manager; Bedrock needs no key, only an IAM role |
| Run log, approvals | CloudWatch Logs (hashes and counts) and the approvals table |
| Kill switch (governance console) | AppConfig feature flag polled by the service |
| Monthly cost threshold | AWS Budgets alert next to the in-app caps |

The Terraform starter in `infra/aws/` creates the parts with no running cost until used: a versioned, encrypted course
content bucket with Object Lock, the build queue with a dead-letter queue, the session secret, and a service role
that can read and write that bucket, use that queue, read its secret, send email from one verified identity and
invoke only the approved Bedrock models. It hasn't been applied to a live account.

What changes inside a firm: sign-in moves to the firm's SSO, so registration is no longer open. Suggestions can come
from employees with their team recorded. The owner role becomes a small group (learning and development, plus a
technical reviewer per course), with two approvers for security-tooling topics.
