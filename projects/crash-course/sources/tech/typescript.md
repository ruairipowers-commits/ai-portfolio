---
title: TypeScript
category: Languages
vendor: Microsoft
docs: https://www.typescriptlang.org/docs/
aliases: [TypeScript]
summary: JavaScript with static types; common for MCP servers, web UIs and Node services.
---

# TypeScript

TypeScript is JavaScript with a static type system, compiled to plain JavaScript, and it is the language many tool and UI ecosystems expect.

## What it is

TypeScript is an open-source language developed by Microsoft. It adds type annotations, interfaces and generics to JavaScript; the compiler (`tsc`) checks them and emits ordinary JavaScript that runs in Node.js or a browser. Types are erased at runtime, so they are a development-time safety net rather than a runtime guarantee.

For a Python-centric data team, the reason to touch TypeScript is usually ecosystem fit: front-end frameworks, many developer tools and a lot of protocol SDKs are TypeScript-first. Writing that piece in the language its ecosystem uses tends to be less work than fighting a port.

Runtime validation still needs a library (for example Zod) at boundaries where data arrives from outside, much as Pydantic does in Python.

## Typical use cases

- Web front ends and dashboards.
- Node.js services and serverless functions.
- MCP servers and other tool integrations whose reference SDK is TypeScript.
- Browser extensions and developer tooling.
- Shared type definitions between a front end and an API.

## In AI work

TypeScript shows up at the edges of AI systems: chat front ends, tool servers that agents call, and serverless handlers that sit in front of a model. The Model Context Protocol has an official TypeScript SDK, so a tool server can be written once in TypeScript and used by Python agents or desktop clients over stdio. Static types on tool inputs make the tool contract explicit, which helps when a model is choosing which tool to call.

## In this portfolio

- The [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md) gets its tools from an [MCP](mcp.md) server written in TypeScript with `@modelcontextprotocol/sdk` over stdio, loaded into the [Python](python.md) LangGraph agent via `langchain-mcp-adapters`.

## Pros and cons

| Pros | Cons |
|---|---|
| Catches type errors before runtime | Types vanish at runtime; boundaries still need validation |
| First-class editor support (autocomplete, refactoring) | Build step and `tsconfig` settings add setup |
| Huge npm ecosystem; reference SDK for many protocols | npm dependency trees get deep quickly |
| Same language across browser and server | A second language and toolchain for a Python data team |

## Basic usage

A typed function compiled and run with Node.js:

```typescript
// break.ts — compile with: npx tsc break.ts && node break.js
interface Break {
  account: string;
  expected: number;
  actual: number;
}

function difference(b: Break): number {
  return b.actual - b.expected;
}

const b: Break = { account: "FUND-01", expected: 1000, actual: 985 };
console.log(`${b.account}: ${difference(b)}`);
```

## Documentation

[TypeScript documentation](https://www.typescriptlang.org/docs/) — official, from Microsoft.
