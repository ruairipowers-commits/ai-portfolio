---
title: Terraform
category: Infrastructure & delivery
vendor: HashiCorp
docs: https://developer.hashicorp.com/terraform/docs
aliases: [Terraform]
summary: Infrastructure as code — declare cloud resources in HCL, review the plan, apply it.
---

# Terraform

Terraform describes cloud infrastructure as code, shows you a plan of what will change, and then makes those changes.

## What it is

Terraform is an infrastructure-as-code tool from HashiCorp. You write resource definitions in HCL (HashiCorp
Configuration Language) — an S3 bucket, a database, a container service — and Terraform works out the order to create
them in, calls the provider APIs, and records what it built in a state file.

The workflow is three commands: `terraform init` downloads providers, `terraform plan` shows a diff between the code
and what exists, and `terraform apply` executes it. The plan step is the part that matters in a regulated shop: the
change is readable and reviewable before anything touches production.

Providers exist for AWS, Azure, GCP, Cloudflare, GitHub, Datadog and many more, so one tool and one review process can
cover most of an estate.

## Typical use cases

- Standing up repeatable environments (dev, staging, prod) from one set of modules.
- Putting infrastructure changes through the same pull-request review as application code.
- Detecting drift between what is declared and what someone changed by hand in the console.
- Packaging a reference architecture as a module other teams can reuse.
- Tearing a sandbox down cleanly with `terraform destroy`.

## In AI work

AI systems tend to need more moving parts than a typical app: object storage for documents and audit logs, a model
endpoint with tightly scoped IAM permissions, a vector store, a scheduler, alerting. Terraform keeps that list
explicit. The IAM policy that limits which models a service may invoke, and the bucket policy that makes model outputs
immutable, become reviewable lines of code rather than console settings someone has to remember.

It also makes cost containment easier to reason about: everything an experiment created is in the state file and can
be destroyed in one step.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md) ships a Terraform starter for S3, Glue, Athena, Bedrock
  and ECS Fargate.
- [EOD heartbeat](../blog/posts/eod-heartbeat.md) has Terraform for MWAA, RDS, SNS and S3 Object Lock.
- See the [AWS page](aws.md) for what each of those services does.

## Pros and cons

| Pros | Cons |
|---|---|
| Plan before apply: changes are visible and reviewable | State files need care — remote storage, locking, and they can contain secrets |
| One tool across many clouds and SaaS providers | HCL gets awkward for complex logic (loops, conditionals) |
| Large ecosystem of providers and community modules | Provider upgrades occasionally force code changes |
| Drift detection against the real environment | Licence changed from open source to BSL; OpenTofu is the community fork |

## Basic usage

A minimal configuration that creates one S3 bucket:

```hcl
terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "my-team-ai-artifacts-example"
}
```

Then run `terraform init`, `terraform plan`, `terraform apply`.

## Documentation

[Terraform documentation](https://developer.hashicorp.com/terraform/docs) — official, from HashiCorp.
