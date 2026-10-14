---
title: Amazon Bedrock
category: Model providers
vendor: Amazon Web Services
docs: https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html
aliases: [Amazon Bedrock, Bedrock]
summary: AWS's managed service for calling foundation models from many providers inside AWS.
---

# Amazon Bedrock

Amazon Bedrock is a managed AWS service that gives one API to foundation models from several providers, inside your AWS account's security and billing.

## What it is

Bedrock hosts models from Amazon and other providers, including Anthropic and OpenAI. You call them through the `bedrock-runtime` endpoint with the AWS SDK. The Converse API is the recommended, model-neutral interface: the same request shape works across models, so switching providers is mostly a change of model ID. Bedrock also offers provider-compatible APIs (Anthropic Messages, OpenAI Chat Completions) for code already written against those.

Around the models, Bedrock adds managed pieces such as Knowledge Bases for retrieval and options for model customization. Access is controlled with IAM like any other AWS service, and calls show up in your AWS account's logging and billing.

For an investment firm already on AWS, the main draw is governance: model calls stay under existing IAM roles, network controls and audit tooling, and there is one bill and one contract rather than one per model vendor.

## Typical use cases

- Calling Claude or other models from AWS workloads without a separate vendor key.
- Swapping models behind one API for cost or capability tests.
- Managed retrieval (RAG) over documents in S3 with Knowledge Bases.
- Running model calls from ECS, Lambda or Step Functions with IAM roles.
- Keeping AI usage inside an existing cloud security review.

## In AI work

Bedrock is often the production route for a pipeline that was built against a mock or a direct API: the code stays the same behind a model registry, and the AWS deployment points the alias at a Bedrock model ID. That gives the risk team a familiar control surface — IAM policies on who can invoke which model, AWS audit logging of who called what — without new infrastructure.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md): Bedrock is one of the providers behind the model registry (with mock, [Anthropic](anthropic.md) and [OpenAI](openai.md)), and is part of the [Terraform](terraform.md) starter.
- [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md): the AWS path runs the agent on ECS Fargate with Bedrock as the model provider.
- [Research Q&A](../blog/posts/research-qa-rag.md): the AWS path uses Bedrock Knowledge Bases on OpenSearch Serverless.

## Pros and cons

| Pros | Cons |
|---|---|
| Models from several providers behind one API | Model and feature availability varies by region |
| IAM, logging and billing through your AWS account | New models can reach Bedrock later than the provider's own API |
| No separate vendor keys to manage | Managed features (e.g. Knowledge Bases) add AWS lock-in |
| Converse API makes model swaps cheap | Model access and quotas need setting up per account |

## Basic usage

Call a model through the Converse API with boto3 (AWS credentials and model access must already be set up):

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

response = client.converse(
    modelId="anthropic.claude-opus-4-7",
    messages=[{"role": "user", "content": [{"text": "Summarize this vendor note in three bullets: ..."}]}],
)

print(response["output"]["message"]["content"][0]["text"])
```

## Documentation

[Amazon Bedrock documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html) — official, from Amazon Web Services. See also [Get started with the API](https://docs.aws.amazon.com/bedrock/latest/userguide/getting-started-api.html).
