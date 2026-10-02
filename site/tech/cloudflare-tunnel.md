---
title: Cloudflare Tunnel
category: Infrastructure & delivery
vendor: Cloudflare
docs: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
aliases: [Cloudflare Tunnel]
summary: Publish a private server to the internet with outbound-only connections — no open ports.
---

# Cloudflare Tunnel

Cloudflare Tunnel connects a server to Cloudflare's network through outbound-only connections, so you can publish it
without a public IP address or any open inbound ports.

## What it is

A small daemon, `cloudflared`, runs next to your service. It opens outbound connections to Cloudflare, and Cloudflare
routes requests for your hostname down those connections. Your firewall can block all inbound traffic; the origin
server is never directly reachable from the internet.

Because traffic passes through Cloudflare first, you get its edge features in front of the origin: TLS, caching, DDoS
protection, and — through Cloudflare Access — identity-based login in front of an app without changing the app.

Tunnels can be created from the dashboard or the CLI, and one tunnel can serve several hostnames.

## Typical use cases

- Publishing a home lab or on-prem service without port forwarding.
- Exposing internal tools to staff behind single sign-on (with Cloudflare Access).
- Replacing a VPN for access to a few specific web apps.
- Giving a temporary public URL to a local dev server.
- Hiding an origin's IP address from direct attack.

## In AI work

AI prototypes often need to run on hardware you control — a GPU box, a server holding data you can't move to a public
cloud — while still being reachable by reviewers or business users. A tunnel lets you share them without opening the
network. Adding Cloudflare Access in front means only named people can reach an app that spends model tokens or shows
sensitive output.

## In this portfolio

- The live demos run in [Docker](docker.md) containers on a home server behind [Caddy](caddy.md); Cloudflare Tunnel
  carries public traffic to Caddy without opening ports on the home network.
- That includes demos such as [Research Q&A](../blog/posts/research-qa-rag.md) and
  [EOD heartbeat](../blog/posts/eod-heartbeat.md).

## Pros and cons

| Pros | Cons |
|---|---|
| No inbound ports or public IP needed | All traffic depends on Cloudflare's availability and terms |
| Origin IP stays hidden | Your domain's DNS needs to be on Cloudflare for the standard setup |
| Pairs with Cloudflare Access for SSO in front of apps | Cloudflare terminates TLS, so it can see the traffic |
| Simple to run: one daemon, one config | Large uploads and long-lived requests are subject to edge limits |

## Basic usage

Create a named tunnel, point a hostname at it, and run it against a local service:

```bash
cloudflared tunnel login
cloudflared tunnel create demo
cloudflared tunnel route dns demo demo.example.com
cloudflared tunnel run --url http://localhost:8080 demo
```

## Documentation

[Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
— official, from Cloudflare.
