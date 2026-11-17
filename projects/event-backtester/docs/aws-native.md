# Running event-backtester AWS-native

Same package, C++ kernel, prompts, evals and governance config. What changes is where each piece runs.

```mermaid
flowchart LR
    subgraph Local["Local (default)"]
        L1[data/ticks/*.parquet] --> L2[engine + C++ kernel]
        L2 --> L3[(SQLite audit)]
        L2 --> L4[mock / Anthropic / OpenAI]
    end
    subgraph AWS["AWS-native"]
        A1[S3 Parquet ticks<br/>+ Athena] --> A2[ECS Fargate task<br/>same container]
        A2 --> A3[Amazon Bedrock<br/>IAM-scoped]
        A1 --> A8[AWS Batch array job<br/>one fold or grid slice each]
        A8 --> A9[Step Functions<br/>walk-forward]
        A2 --> A4[(DynamoDB promotions)]
        A4 --> A5[PM approval<br/>separate role]
        A5 --> A6[S3 Object Lock<br/>promotion records]
        A7[AWS Budgets] -.-> A2
    end
```

| Concern | Local | AWS-native | Change required |
|---|---|---|---|
| Tick data | Parquet files | S3 (partitioned by date) + Athena for exploration | read with `pd.read_parquet("s3://…")` (s3fs) |
| Backtests | one process | ECS Fargate task; large sweeps as AWS Batch array jobs, walk-forward as a Step Functions Map over folds | split the grid by index (the kernel's sweep already takes lists) |
| Model | `memo-primary: mock-local` | Bedrock | set `bedrock-claude.model_id` + pricing, eval, `promote` |
| Secrets | `.env` | IAM task role | none |
| Decisions | SQLite `promotions` | DynamoDB (task writes requests; only the PM role writes decisions) + S3 Object Lock records | write via boto3 (next increment) |
| Budgets | `cost.*` | same **plus** AWS Budgets forecast alert | set `monthly_budget_usd`, `alert_email` |

## Steps

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform plan          # starter: review before apply
docker build -t event-backtester . && docker push <ecr-url>:latest
```

The Terraform is a reviewed starter, not applied to a live account.
