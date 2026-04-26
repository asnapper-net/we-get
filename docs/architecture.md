# Architecture

See [../CLAUDE.md](../CLAUDE.md) for the authoritative architecture document.

This file holds supplementary diagrams and notes generated during implementation.

## Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    EXISTING ENTERPRISE STACK                     │
│   GitHub │ Confluence │ Jira │ Kubernetes │ ArgoCD               │
└──────────────────────────────────────────────────────────────────┘
                              ↕  (MCP servers)
┌──────────────────────────────────────────────────────────────────┐
│                    AGENT PLATFORM                                │
│                                                                  │
│  Orchestrator (LangGraph)   Approval Service   PR Orchestrator  │
│  PM  Architect  Engineer    QA  Reviewer  DevOps                │
│                                                                  │
│  RabbitMQ │ Postgres │ Qdrant │ MinIO │ Langfuse                │
└──────────────────────────────────────────────────────────────────┘
                              ↕
┌──────────────────────────────────────────────────────────────────┐
│  Claude API (primary)     Embeddings (Voyage or OpenAI)          │
└──────────────────────────────────────────────────────────────────┘
```

## Workflow State Machine

```
intake → design → [await_arch_approval] → implementation
       → review → [await_pr_approval] → deploy → done
                                       ↘ failed (after 3 cycles)
```
