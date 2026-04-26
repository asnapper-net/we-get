# agent-platform

Autonomous multi-agent platform for enterprise software development. Agents handle the full SDLC (PM → Architect → Engineer → QA → Reviewer → DevOps) with humans only at defined approval gates.

See [CLAUDE.md](./CLAUDE.md) for the full architecture, component specs, and implementation roadmap.

## Quick start (local dev)

```bash
# Start backing services
docker compose up -d

# Install dependencies (requires uv)
uv sync --all-packages

# Run orchestrator
cd orchestrator && uv run uvicorn orchestrator.server:app --reload
```

## Namespaces

| Namespace | Workloads |
|---|---|
| `agents-platform` | RabbitMQ, Postgres, Qdrant, MinIO, Langfuse |
| `agents-mcp` | All MCP servers |
| `agents-runtime` | Orchestrator, long-lived agents (PM, DevOps) |
| `agents-jobs` | Ephemeral agent Jobs (Engineer, QA) |
| `agents-services` | Approval service, PR orchestrator |
