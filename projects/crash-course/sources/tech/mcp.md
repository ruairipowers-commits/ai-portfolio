---
title: Model Context Protocol (MCP)
category: Orchestration & agents
vendor: Model Context Protocol project (open source)
docs: https://modelcontextprotocol.io/
aliases: [Model Context Protocol, MCP]
summary: Open protocol for exposing tools and data to AI applications through a standard server.
---

# Model Context Protocol (MCP)

MCP is an open standard for connecting AI applications to tools and data: you write a server once, and any MCP-capable client can discover and call it.

## What it is

MCP has three participants. A host is the AI application (an IDE, a chat app, your own agent). The host creates one client per connection, and each client talks to one server. Servers expose three kinds of things: tools (functions the model can call), resources (data the application can read) and prompts (reusable templates). Messages are JSON-RPC 2.0.

There are two transports. Stdio runs the server as a local child process and talks over standard input and output, with no network involved. Streamable HTTP serves remote clients over HTTP and supports standard authentication. The protocol layer is the same over both, so a server can start local and move behind HTTP later.

The project publishes the specification and official SDKs in several languages, including TypeScript and Python, plus a reference set of servers and an inspector tool.

## Typical use cases

- Giving an agent a fixed, reviewed set of tools instead of ad-hoc function code.
- Wrapping an internal system (a database, a ticketing API) once and reusing it across clients.
- Keeping tool code in a different language or process from the agent.
- Letting developer tools such as IDEs reach internal context.
- Describing each tool's inputs with JSON Schema so calls are validated.

## In AI work

MCP moves the tool boundary out of the prompt and into a separate process with a declared interface. That matters for control: the list of tools is something you can review, version and test on its own, and each tool's input schema is enforced before your code runs. It does not decide what the model is allowed to do with those tools — approval, rate limits and logging still belong in the host or the server.

## In this portfolio

- [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md): the agent's tools come from an MCP server written in [TypeScript](typescript.md) with `@modelcontextprotocol/sdk` over stdio, loaded into the [LangGraph](langgraph.md) agent through langchain-mcp-adapters.

## Pros and cons

| Pros | Cons |
|---|---|
| One tool server works with many clients | Another process and protocol to run and debug |
| Tool interfaces are explicit and schema-checked | The protocol is still evolving between versions |
| Language-neutral: tools need not be in Python | Security of what a tool does is still on you |
| Stdio needs no network for local use | Third-party servers need the same vetting as any dependency |

## Basic usage

A minimal stdio server with one tool, using the TypeScript SDK:

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "my-server", version: "1.0.0" });

server.registerTool(
  "add",
  {
    title: "Add",
    description: "Add two numbers",
    inputSchema: { a: z.number(), b: z.number() },
  },
  async ({ a, b }) => ({
    content: [{ type: "text", text: String(a + b) }],
  })
);

const transport = new StdioServerTransport();
await server.connect(transport);
```

## Documentation

[Model Context Protocol documentation](https://modelcontextprotocol.io/) — official, from the Model Context Protocol project. See also the [TypeScript SDK server guide](https://ts.sdk.modelcontextprotocol.io/documents/server.html).
