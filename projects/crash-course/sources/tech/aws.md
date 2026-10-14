---
title: AWS
category: Cloud (AWS)
vendor: Amazon Web Services
docs: https://docs.aws.amazon.com/
aliases: []
summary: The AWS services each project's production path maps to, with what each one is for.
services: [S3, S3 Object Lock, Athena, Glue, ECS Fargate, Lambda, App Runner, RDS, Aurora Serverless, MWAA, Step Functions, SNS, SES, Secrets Manager, AppConfig, Kinesis Data Firehose, OpenSearch Serverless, Bedrock Knowledge Bases, CloudWatch, AWS Budgets]
---

# AWS services used in this portfolio

Every project runs offline on a laptop, and each one also documents an AWS path: the managed services I would use to
run it in production at an investment firm.

Each section below says what the service is, where it fits in AI work, one honest pro and con, and links to the
official AWS documentation. Model access itself is covered on the [Bedrock](bedrock.md) page; the infrastructure code
is [Terraform](terraform.md).

## S3

Amazon S3 is object storage: files of any size in buckets, addressed by key. It is the default landing zone for raw
data, documents and model artifacts, and in this portfolio it holds vendor samples for
[Alt-data vendor triage](../blog/posts/altdata-triage.md) and the audit trail for the
[governance console](../blog/posts/governance-console.md).

- **Pro:** cheap, durable, and every other AWS data service reads from it.
- **Con:** bucket policies and IAM interact in ways that make access mistakes easy.

[Amazon S3 documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)

## S3 Object Lock

Object Lock stores objects in write-once-read-many (WORM) mode for a retention period, so they cannot be overwritten
or deleted. It is the usual control for records that must be provably unaltered — such as audit records of what a model was asked and
answered. Both [EOD heartbeat](../blog/posts/eod-heartbeat.md) and the governance console use it on AWS.

- **Pro:** immutability is enforced by the storage layer, not by application code.
- **Con:** compliance-mode retention cannot be shortened, even by the account root — mistakes are expensive.

[S3 Object Lock documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)

## Athena

Athena runs SQL directly over files in S3, with no cluster to manage. It suits ad hoc analysis of logs and data
samples; the governance console's AWS path queries its event history this way, and the alt-data triage Terraform starter
includes it.

- **Pro:** pay per query, nothing to run when idle.
- **Con:** cost and speed depend on file layout — unpartitioned CSV gets slow and expensive.

[Amazon Athena documentation](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)

## Glue

AWS Glue is a serverless data-integration service; its Data Catalog stores table definitions that Athena and other
engines use to query S3. The [Alt-data vendor triage](../blog/posts/altdata-triage.md) Terraform starter includes Glue
alongside S3 and Athena.

- **Pro:** one shared catalog across Athena, EMR and Redshift Spectrum.
- **Con:** Glue ETL jobs are Spark-based and heavy for small transformations.

[AWS Glue documentation](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)

## ECS Fargate

ECS on Fargate runs [Docker](docker.md) containers without managing servers. It is the natural home for a
containerized AI app or agent worker; alt-data triage and the
[Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md) both target it.

- **Pro:** no EC2 instances to patch; scale by task count.
- **Con:** more setup (VPC, load balancer, task definitions) than simpler container hosts.

[Amazon ECS on AWS Fargate documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)

## Lambda

Lambda runs functions in response to events, billed per invocation and duration. In AI systems it fits small glue
steps — reacting to a file landing in S3, calling a model on one record, posting an alert — rather than long-running
agents. None of the current projects depend on it.

- **Pro:** zero idle cost and no servers.
- **Con:** execution time limits and cold starts make it a poor fit for long or heavy model calls.

[AWS Lambda documentation](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)

## App Runner

App Runner deploys a web service from a container image or source repo and handles load balancing, TLS and scaling.
It is the simplest way to host an internal AI web app; the governance console's AWS path uses it.

- **Pro:** almost no infrastructure to define.
- **Con:** fewer networking and tuning options than ECS — and AWS has closed App Runner to new customers, so a new
  deployment of the console would use ECS Fargate instead.

[AWS App Runner documentation](https://docs.aws.amazon.com/apprunner/latest/dg/what-is-apprunner.html)

## RDS

Amazon RDS is managed relational databases, including PostgreSQL. EOD heartbeat uses it for Postgres with pgvector
(runbook retrieval alongside break data), and the trade-ops agent uses it for state when Postgres replaces SQLite.

- **Pro:** backups, patching and failover handled for you.
- **Con:** you still size and pay for instances while idle.

[Amazon RDS documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Welcome.html)

## Aurora Serverless

Aurora Serverless v2 is Aurora (PostgreSQL- or MySQL-compatible) that scales capacity up and down with load. It suits
spiky internal tools; the governance console's event store uses it on AWS.

- **Pro:** capacity follows demand without manual resizing.
- **Con:** pricing is harder to predict than a fixed instance.

[Aurora Serverless v2 documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html)

## MWAA

Amazon Managed Workflows for Apache Airflow runs Airflow without operating the scheduler and workers yourself.
[EOD heartbeat](../blog/posts/eod-heartbeat.md)'s DAG, which runs every five minutes through the evening, maps to it.

- **Pro:** existing Airflow DAGs move over largely unchanged.
- **Con:** an environment has a standing cost even when no DAGs are running.

[Amazon MWAA documentation](https://docs.aws.amazon.com/mwaa/latest/userguide/what-is-mwaa.html)

## Step Functions

Step Functions orchestrates multi-step workflows as state machines. Its `waitForTaskToken` pattern pauses a workflow
until a callback arrives, which is how the trade-ops agent's human approval step maps to AWS.

- **Pro:** durable waits and retries without writing that logic yourself.
- **Con:** state-machine definitions are verbose and awkward to test locally.

[AWS Step Functions documentation](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)

## SNS

Amazon SNS is pub/sub messaging that fans a message out to email, SMS, queues or functions. EOD heartbeat's AWS path
uses it for alerts.

- **Pro:** one publish reaches many subscribers and channels.
- **Con:** formatting and delivery control for email are basic.

[Amazon SNS documentation](https://docs.aws.amazon.com/sns/latest/dg/welcome.html)

## SES

Amazon SES sends transactional email at scale. It fits AI systems that need formatted notifications — such as the
governance console's escalation emails — though the console's current AWS path does not specify it.

- **Pro:** full control over email content and sender domain.
- **Con:** new accounts start in a sandbox and need approval and DNS setup before sending freely.

[Amazon SES documentation](https://docs.aws.amazon.com/ses/latest/dg/Welcome.html)

## Secrets Manager

Secrets Manager stores credentials and API keys, with access controlled by IAM and optional rotation. Model provider
keys belong here; the governance console's AWS path uses it.

- **Pro:** keys stay out of code, images and environment files.
- **Con:** charged per secret and per API call, which adds up with many small secrets.

[AWS Secrets Manager documentation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)

## AppConfig

AWS AppConfig deploys configuration and feature flags to running apps with validation and gradual rollout. It is in
the governance console's AWS path, and it suits a kill switch: a workflow can be turned off without a redeploy.

- **Pro:** config changes are validated, staged and can roll back.
- **Con:** apps must poll or use the agent to pick up changes, adding a small delay.

[AWS AppConfig documentation](https://docs.aws.amazon.com/appconfig/latest/userguide/what-is-appconfig.html)

## Kinesis Data Firehose

Amazon Data Firehose (formerly Kinesis Data Firehose) streams records into destinations such as S3 in batches. The
governance console's AWS design sends its event stream through Firehose to S3, where Athena queries it (designed,
not yet wired into the code).

- **Pro:** no consumers to write; batching and delivery are managed.
- **Con:** buffering means events land with a delay, not instantly.

[Amazon Data Firehose documentation](https://docs.aws.amazon.com/firehose/latest/dev/what-is-this-service.html)

## OpenSearch Serverless

OpenSearch Serverless provides OpenSearch collections — including vector search — without managing a cluster. It is
the vector store behind Bedrock Knowledge Bases in [Research Q&A](../blog/posts/research-qa-rag.md)'s AWS path.

- **Pro:** keyword and vector search in one managed service.
- **Con:** has a minimum capacity charge, which is significant for small workloads.

[Amazon OpenSearch Serverless documentation](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)

## Bedrock Knowledge Bases

Bedrock Knowledge Bases is managed retrieval-augmented generation: it chunks and embeds documents from S3, stores them
in a vector store, and retrieves passages for a model to cite. It replaces Research Q&A's local SQLite retrieval on AWS.

- **Pro:** ingestion, embedding and retrieval without writing the pipeline.
- **Con:** less control over chunking and ranking than a hand-built hybrid search.

[Amazon Bedrock Knowledge Bases documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)

## CloudWatch

Amazon CloudWatch collects logs, metrics and alarms across AWS services. For AI apps it is where latency, error rates
and token-usage metrics would be graphed and alarmed; it is the default place to look once any of the projects is deployed.

- **Pro:** built in to almost every AWS service by default.
- **Con:** log ingestion and retention costs grow quickly if left unchecked.

[Amazon CloudWatch documentation](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html)

## AWS Budgets

AWS Budgets tracks spend against thresholds you set and alerts when actual or forecast cost crosses them. Model
inference costs can move fast, so a budget alert is a sensible backstop next to in-app cost limits.

- **Pro:** simple to set up and alerts before the invoice does.
- **Con:** billing data lags, so it is a backstop, not a real-time stop.

[AWS Budgets documentation](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)

## Documentation

[AWS documentation](https://docs.aws.amazon.com/) — official, from Amazon Web Services.
