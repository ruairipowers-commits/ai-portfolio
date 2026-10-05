# AWS-native path — editorial-agents

| Piece | Here (self-hosted) | AWS-native |
|---|---|---|
| Scout schedule | In-process scheduler | EventBridge Scheduler → Lambda (daily) |
| Sources | httpx from the host | Lambda in a VPC with a NAT egress allow-list |
| Classifier | Ollama (local) or mock | Bedrock (a small model) behind the same alias |
| Queue + runs | SQLite on a volume | DynamoDB (topics, actions, runs) |
| Owner email and links | SMTP (Resend) + signed links to the service | SES + API Gateway → Lambda for the confirm/POST |
| Writer + editor | Scheduled Claude task, PR to GitHub | Same (it isn't hosted), or a Step Functions workflow calling Bedrock |
| Draft email | GitHub Action | Same |
| Subscribers | Site assistant (SQLite) | DynamoDB + SES, with SES suppression list |
| Kill switch, telemetry | Governance console | Same console, or CloudWatch + an SSM parameter as the switch |

Costs at this scale are pennies a month on AWS (a few Lambda runs a day, tiny DynamoDB tables, a handful of emails),
plus Bedrock tokens if the classifier moves there. See `infra/aws/` for a starter.
