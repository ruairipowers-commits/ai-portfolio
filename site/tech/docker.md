---
title: Docker
category: Infrastructure & delivery
vendor: Docker, Inc.
docs: https://docs.docker.com/
aliases: [Docker Compose, docker compose, Docker]
summary: Containers — package an app with its dependencies and run it the same way anywhere.
---

# Docker

Docker packages an application and everything it needs into a container image that runs the same way on a laptop, a
home server or a cloud service.

## What it is

A `Dockerfile` lists the steps to build an image: a base OS layer, system packages, your code, and the command to
start it. `docker build` produces the image; `docker run` starts a container from it. Images are pushed to a registry
(Docker Hub, GitHub Container Registry, Amazon ECR) and pulled wherever they need to run.

Docker Compose describes several containers that work together — an app, a database, a scheduler — in one
`compose.yaml` (or `docker-compose.yml`) file, so `docker compose up` starts the whole stack with its networks and
volumes.

The image is the unit of deployment for most managed container services, including ECS Fargate and App Runner on AWS.

## Typical use cases

- Reproducible dev environments: "works on my machine" becomes "works in the image".
- Running a multi-service stack locally with Docker Compose.
- Shipping one artifact through test, staging and production.
- Isolating apps from each other on a shared server.
- Pinning system libraries that Python packages depend on.

## In AI work

AI apps often have awkward dependencies — native libraries for PDF parsing, database extensions such as vector search,
specific Python versions. Baking them into an image removes a whole class of deployment surprises. It also gives you a
clean boundary for security: the container runs as a non-root user, holds only the files it needs, and receives model
API keys as environment variables at runtime rather than in the image.

For evaluation work, an image tag is a precise record of which code produced which results.

## In this portfolio

- The live demos run in Docker containers on a home server behind [Caddy](caddy.md) and a
  [Cloudflare Tunnel](cloudflare-tunnel.md).

- The same projects can instead be deployed to [Hugging Face Spaces](hugging-face-spaces.md).
- On AWS, [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md) and
  [Alt-data vendor triage](../blog/posts/altdata-triage.md) target ECS Fargate, which runs container images.

## Pros and cons

| Pros | Cons |
|---|---|
| Same artifact runs everywhere | Images get large without care (multi-stage builds, slim bases) |
| Compose makes multi-service stacks one command | Docker Desktop requires a paid licence for larger companies |
| Standard input to every managed container platform | Base images need regular patching for CVEs |
| Clean isolation between apps on one host | Persistent data needs explicit volumes or it is lost on rebuild |

## Basic usage

A minimal Dockerfile for a Streamlit app:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
USER nobody
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
```

Build and run it with `docker build -t demo .` then `docker run -p 8501:8501 demo`.

## Documentation

[Docker documentation](https://docs.docker.com/) — official, from Docker, Inc.
