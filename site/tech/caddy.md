---
title: Caddy
category: Infrastructure & delivery
vendor: Caddy project
docs: https://caddyserver.com/docs/
aliases: [Caddy]
summary: Web server and reverse proxy with automatic HTTPS and a short, readable config.
---

# Caddy

Caddy is a web server and reverse proxy that obtains and renews TLS certificates automatically and is configured with a
short, readable file.

## What it is

Caddy is a single Go binary. Its configuration, the Caddyfile, maps site addresses to handlers: serve static files,
reverse-proxy to an app on a local port, add headers, apply basic auth. A complete reverse-proxy config is often three
lines.

Its best-known feature is automatic HTTPS: for a public domain name it requests a certificate from a certificate
authority, installs it and renews it without any extra tooling. There is also a JSON config and an admin API for
changing config at runtime, but most setups never need them.

## Typical use cases

- Putting several internal apps behind one entry point, routed by hostname or path.
- Terminating TLS in front of an app server (Streamlit, FastAPI, a dashboard).
- Serving a static site.
- Adding security headers, compression and access logs in one place.
- Simple authentication in front of an internal tool.

## In AI work

Most AI demos and internal tools are a handful of small web apps — a chat UI, an API, an admin console. A reverse
proxy gives them one front door, which is where you want cross-cutting controls: request logging, rate limits, size
limits on uploads, and authentication before anyone reaches an endpoint that spends model tokens. Caddy keeps that
layer small enough to review at a glance.

Streamlit and similar apps use WebSockets; Caddy's `reverse_proxy` handles them without extra configuration.

## In this portfolio

- The live demos run in [Docker](docker.md) containers on a home server; Caddy routes requests to each one, and a
  [Cloudflare Tunnel](cloudflare-tunnel.md) carries traffic from the internet to Caddy.
- Demos include [Alt-data vendor triage](../blog/posts/altdata-triage.md) and the
  [governance console](../blog/posts/governance-console.md).

## Pros and cons

| Pros | Cons |
|---|---|
| Automatic certificate issuance and renewal | Smaller ecosystem and fewer how-to answers than Nginx |
| Caddyfile is short and easy to review | Advanced features need plugins compiled into a custom build |
| Single binary, sensible secure defaults | Two config formats (Caddyfile and JSON) can confuse at first |
| WebSockets and HTTP/2 work out of the box | Less familiar to many ops teams, so a harder sell in a large estate |

## Basic usage

A Caddyfile that serves one hostname and proxies it to an app on port 8501:

```text
demo.example.com {
    reverse_proxy localhost:8501
}
```

Run it with `caddy run --config Caddyfile`.

## Documentation

[Caddy documentation](https://caddyserver.com/docs/) — official, from the Caddy project.
