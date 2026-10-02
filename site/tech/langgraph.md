---
title: LangGraph
category: Orchestration & agents
vendor: LangChain Inc.
docs: https://docs.langchain.com/oss/python/langgraph/overview
aliases: [LangGraph]
summary: Graph-based framework for stateful agents with checkpoints and human approval steps.
---

# LangGraph

LangGraph is a Python framework for building agents as explicit graphs of steps, with saved state so a run can pause, wait for a person, and resume.

## What it is

LangGraph comes from LangChain Inc. You define a state object, write each step as a plain function (a node) that reads the state and returns updates, and connect the nodes with edges, including conditional edges that route on what the model decided. The point is control: deterministic, hand-written steps and LLM-driven steps sit in the same graph, and you can see exactly which path a run took.

Persistence is the other half. A checkpointer writes the graph state after each step, keyed by a thread ID. That gives you durable execution (a run can resume after a failure), short-term memory across turns, and human-in-the-loop: a node calls `interrupt()`, the run stops with its state saved, and a later call with `Command(resume=...)` and the same thread ID carries on from that exact point.

It is a library, not a hosted service. You choose the checkpointer backend, the model client and where it runs.

## Typical use cases

- Agents that call tools in a loop but must follow a defined workflow.
- Approval gates: pause before any action with side effects and wait for a human decision.
- Long-running processes that need to survive restarts.
- Multi-step pipelines that mix rules, lookups and model calls in one auditable flow.
- Replaying or inspecting a past run from its saved checkpoints.

## In AI work

The common failure in agent projects is not the model; it is an agent that does something nobody approved. LangGraph makes the control flow a reviewable artifact: the graph says which node can write, and an `interrupt()` in front of it means the write cannot happen without a recorded human answer. Checkpoints also give you an audit trail of state per step, which is what a risk or compliance reviewer will ask for.

## In this portfolio

- [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md): a LangGraph agent works trade exceptions and calls `interrupt()` before any write. Its tools come from a TypeScript [MCP](mcp.md) server loaded through langchain-mcp-adapters. State is in [SQLite](sqlite.md) by default with a [Postgres](postgres.md) option; on AWS the approval wait maps to Step Functions `waitForTaskToken`.

## Pros and cons

| Pros | Cons |
|---|---|
| Explicit graph: easy to review which steps can act | More code and concepts than a single prompt loop |
| Built-in checkpoints, resume and `interrupt()` | Checkpointer storage is yours to run and secure |
| Mixes deterministic steps and LLM steps cleanly | Fast-moving API; upgrades need testing |
| Works with any model client, including a mock | Tied to the LangChain ecosystem for adapters and tooling |

## Basic usage

A minimal one-node graph, using a mock model step:

```python
from langgraph.graph import StateGraph, MessagesState, START, END

def mock_llm(state: MessagesState):
    return {"messages": [{"role": "ai", "content": "hello world"}]}

graph = StateGraph(MessagesState)
graph.add_node(mock_llm)
graph.add_edge(START, "mock_llm")
graph.add_edge("mock_llm", END)
graph = graph.compile()

print(graph.invoke({"messages": [{"role": "user", "content": "hi!"}]}))
```

## Documentation

[LangGraph documentation](https://docs.langchain.com/oss/python/langgraph/overview) — official, from LangChain Inc. See also the [interrupts guide](https://docs.langchain.com/oss/python/langgraph/interrupts).
