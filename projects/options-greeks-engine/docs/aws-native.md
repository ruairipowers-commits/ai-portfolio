# Running options-greeks-engine AWS-native

Same package, C++ engine, prompts, evals and governance config. What changes is where each piece runs.

```mermaid
flowchart LR
    subgraph Local["Local (default)"]
        L1[request text] --> L2[workflow + C++ engine]
        L2 --> L3[(SQLite tickets)]
        L2 --> L4[mock / Anthropic / OpenAI]
    end
    subgraph AWS["AWS-native"]
        A1[Request API<br/>API Gateway] --> A2[Fargate task or Lambda<br/>same container]
        A2 --> A3[Amazon Bedrock<br/>IAM-scoped]
        A2 --> A4[(DynamoDB tickets)]
        A4 --> A5[Step Functions approval<br/>task token, approver role]
        A5 --> A6[S3 Object Lock<br/>approved tickets]
        A7[AWS Budgets] -.-> A2
    end
```

| Concern | Local | AWS-native | Change required |
|---|---|---|---|
| Reference data | YAML in git | S3 (versioned) loaded per session; a vendor feed later | point `market_file` at the S3 copy |
| Engine | wheel built from `cpp/` | same wheel in the image | none |
| Model | `parse-primary` / `explain-primary` → mock | Bedrock (a small model for parsing, a larger one for explanations) | set models + pricing, eval, `promote` |
| Approval | the app's approval tab | Step Functions with a task token: only the approver role can send the token back | wire `decide()` to `SendTaskSuccess` (next increment) |
| Tickets | SQLite | DynamoDB + S3 Object Lock for approved tickets | write via boto3 |
| Budgets | `cost.*` | same **plus** AWS Budgets | set `monthly_budget_usd`, `alert_email` |

## Steps

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform plan          # starter: review before apply
docker build -t options-greeks-engine . && docker push <ecr-url>:latest
```

The Terraform is a reviewed starter, not applied to a live account. Nothing in this design routes orders to a broker.
