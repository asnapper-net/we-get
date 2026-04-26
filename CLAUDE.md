# Autonomous Agent Platform for Enterprise Software Development

This document is the master plan for building an autonomous multi-agent system that handles enterprise software development tasks (project management, architecture, engineering, QA, DevOps) with humans only at approval gates.

This file is the source of truth. When implementing, update it as decisions are made or refined.

---

## 1. Goal & Scope

Build a multi-agent platform that autonomously executes the software development lifecycle for enterprise IT projects, with human oversight only at well-defined approval gates. Agents are responsible for:

- **PM Agent** — ticket intake, decomposition, status reporting
- **Architect Agent** — design proposals, ADRs, diagrams
- **Engineer Agent** — code implementation, PR creation
- **QA Agent** — test generation, test execution, PR-level QA review
- **Reviewer Agent** — code review (architecture, security, quality) on PRs
- **DevOps Agent** — deployment via GitOps, monitoring, incident response

Humans approve transitions between major phases (post-design, post-PR, post-deploy-to-prod) and must approve every feature-branch merge after both agents have approved.

---

## 2. Existing Enterprise Stack (Already Selected — Do Not Replace)

| Concern | Tool |
|---|---|
| Source code | GitHub |
| Specifications / docs | Confluence |
| Issue tracking | Jira |
| Runtime | Kubernetes |
| CI/CD | ArgoCD (GitOps) |

All new platform components run on Kubernetes and are deployed via ArgoCD.

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    EXISTING ENTERPRISE STACK                     │
│   GitHub │ Confluence │ Jira │ Kubernetes │ ArgoCD               │
└──────────────────────────────────────────────────────────────────┘
                              ↕
┌──────────────────────────────────────────────────────────────────┐
│                    AGENT PLATFORM (THIS PROJECT)                 │
│                                                                  │
│   Orchestration │ Event Bus │ State Store │ Agent Runtime        │
│   Observability │ Secrets   │ Guardrails  │ Approval Service     │
└──────────────────────────────────────────────────────────────────┘
                              ↕
┌──────────────────────────────────────────────────────────────────┐
│                    LLM PROVIDERS                                 │
│   Claude API (primary)         Embeddings (Voyage or OpenAI)     │
└──────────────────────────────────────────────────────────────────┘
```

### Interaction patterns used

- **Hierarchical orchestration** for control flow (LangGraph supervisor with agent nodes)
- **Event-driven coordination** via RabbitMQ (agents react to events; not polling)
- **Shared state layer** (Postgres + Qdrant) as the persistent "blackboard"
- **Peer review** between agents (Engineer → QA → Reviewer)
- **Human-in-the-loop at boundaries** (gated approvals via Slack)

Kafka/RabbitMQ alone is *not* the blackboard — it's the nervous system. State lives in Postgres + Qdrant + GitHub/Jira/Confluence.

---

## 4. Component Inventory

### 4.1 Foundation Infrastructure (off-the-shelf, deployed via Helm/operators)

| Component | Choice | Deployment |
|---|---|---|
| Event bus | RabbitMQ (Cluster Operator) | 3-node StatefulSet, namespace `agents-platform` |
| Structured state | PostgreSQL (CloudNativePG) | HA cluster, namespace `agents-platform` |
| Vector DB | Qdrant | Helm chart, namespace `agents-platform` |
| Object storage | MinIO (or cloud S3) | Helm chart or use cloud-managed |
| LLM observability | Langfuse (self-hosted) | Helm chart, namespace `agents-platform` |
| Secrets | External Secrets Operator + existing vault | Cluster-wide |
| Guardrails | NeMo Guardrails or Guardrails AI | Sidecar to each agent |

### 4.2 MCP Servers (mostly off-the-shelf)

| MCP Server | Source | Notes |
|---|---|---|
| GitHub | Official `github-mcp-server` | Off-the-shelf |
| Jira + Confluence | `mcp-atlassian` (community) | Off-the-shelf, single package |
| Kubernetes | `mcp-server-kubernetes` | Off-the-shelf — **also covers ArgoCD** (see §4.3) |
| Slack | Official MCP server | Off-the-shelf |
| Filesystem / code execution | Anthropic reference servers | Off-the-shelf |
| Playwright (for QA) | Official Playwright MCP | Off-the-shelf |

All MCP servers run as Deployments in namespace `agents-mcp`. Agents reach them via internal Service DNS.

### 4.3 ArgoCD Access — No Custom MCP Server Needed

**Important architectural decision:** ArgoCD stores all state as Kubernetes CRDs (`Application`, `AppProject`, `ApplicationSet`). The Kubernetes MCP server reads all of this natively. We do **not** build a custom ArgoCD MCP server.

The DevOps Agent operates GitOps-style via the Kubernetes MCP server:
- **List/inspect apps:** read `Application` CRs
- **Deploy:** patch `.spec.source.targetRevision` on the `Application` CR
- **Trigger sync:** patch the `operation:` field on the `Application` CR
- **Rollback:** patch `targetRevision` back to the previous git SHA
- **Refresh:** set the `argocd.argoproj.io/refresh` annotation

The agent's system prompt **must** explicitly teach the GitOps mental model:
> "You operate via GitOps. To deploy, modify the Application CR's targetRevision; do not invoke imperative `argocd app sync` commands. The CR is the source of truth."

If we later need rollback-by-history-id or operation termination, we'll build a tiny 2-tool MCP server then. Probably never.

### 4.4 Custom Components (what we actually build)

| Component | Approx LOC | Language |
|---|---|---|
| Orchestrator (LangGraph workflow + FastAPI server) | 2000–3000 | Python |
| Each agent (prompt + tools + validators) | 300–700 each | Python |
| Approval Service (Slack-based) | ~400 | Python (FastAPI) |
| PR Orchestrator (GitHub webhook listener) | ~600 | Python (FastAPI) |
| Guardrail rules | ~200 | YAML/Python |
| Helm charts / ArgoCD ApplicationSets | — | YAML |

Total custom code: roughly 5–7k LOC.

---

## 5. Repository Structure

Single monorepo named `agent-platform`:

```
agent-platform/
├── CLAUDE.md                          # This file
├── README.md
├── pyproject.toml                     # Workspace-level config
├── docker-compose.yml                 # Local dev (rabbitmq + postgres + qdrant)
│
├── orchestrator/                      # LangGraph workflow + API server
│   ├── pyproject.toml
│   ├── src/orchestrator/
│   │   ├── state.py                   # ProjectState TypedDict
│   │   ├── graph.py                   # LangGraph definition
│   │   ├── server.py                  # FastAPI: /workflows endpoints
│   │   ├── nodes/                     # Wrappers around agents as graph nodes
│   │   └── routing.py                 # Conditional edge logic
│   └── tests/
│
├── agents/                            # One package per agent
│   ├── _base/                         # Shared agent class, MCP client setup
│   ├── pm/
│   ├── architect/
│   ├── engineer/                      # Wraps Claude Code headless
│   ├── qa/
│   ├── reviewer/
│   └── devops/
│
├── services/
│   ├── approval-service/              # Slack <-> orchestrator bridge
│   └── pr-orchestrator/               # GitHub webhook listener
│
├── mcp-servers/                       # Custom MCP servers (currently empty — see §4.3)
│
├── infrastructure/                    # All K8s manifests / Helm values
│   ├── platform/                      # RabbitMQ, Postgres, Qdrant, Langfuse, MinIO
│   ├── mcp/                           # MCP server deployments
│   ├── runtime/                       # Orchestrator + agent deployments
│   └── argocd-apps/                   # ArgoCD ApplicationSets
│
├── tests/
│   ├── integration/
│   └── e2e/
│
└── docs/
    ├── architecture.md
    ├── runbooks/
    └── prompts/                       # Versioned agent prompts
```

---

## 6. Deployment Topology

| Namespace | Workloads | Type |
|---|---|---|
| `agents-platform` | RabbitMQ, Postgres, Qdrant, MinIO, Langfuse | Stateful, off-the-shelf |
| `agents-mcp` | All MCP servers | Stateless Deployments |
| `agents-runtime` | Orchestrator, long-lived agents (PM, DevOps) | Deployments |
| `agents-jobs` | Ephemeral agent Jobs (Engineer, QA test runs) | Kubernetes Jobs |
| `agents-services` | Approval service, PR orchestrator | Deployments + Ingress |

The platform deploys itself via ArgoCD: there's an `agent-platform` ArgoCD `ApplicationSet` watching `infrastructure/argocd-apps/`.

---

## 7. The Orchestrator (LangGraph)

### 7.1 State schema

```python
# orchestrator/src/orchestrator/state.py
from typing import TypedDict, Literal, Optional

class ProjectState(TypedDict):
    # Identifiers
    jira_ticket_id: str
    github_repo: str
    workflow_run_id: str

    # Artifacts
    requirements_doc: Optional[str]
    architecture_decision: Optional[str]
    pr_url: Optional[str]
    test_results: Optional[dict]
    deployment_status: Optional[str]

    # Control flow
    current_phase: Literal["intake", "design", "implementation",
                           "review", "deploy", "done", "failed"]
    approval_required: bool
    approval_granted: Optional[bool]

    # Memory / control
    messages: list
    errors: list
    retry_count: int
```

### 7.2 Graph structure

Nodes (in order): `pm` → `architect` → `await_arch_approval` → `engineer` → `qa` → `reviewer` → `await_pr_approval` → `devops` → END.

Conditional edges:
- `await_arch_approval`: if approved → `engineer`; if rejected → back to `architect`
- `reviewer`: if tests/issues → back to `engineer`; if retry_count ≥ 3 → fail; else → `await_pr_approval`
- `await_pr_approval`: if approved → `devops`; else END

Compile with `interrupt_before=["await_arch_approval", "await_pr_approval"]` so the workflow pauses for human input. Checkpoint to Postgres via `PostgresSaver`.

### 7.3 API surface

`orchestrator/server.py` exposes:
- `POST /workflows` — start a new workflow (called by Jira webhook)
- `POST /workflows/{id}/resume` — resume after approval (called by approval service)
- `GET /workflows/{id}` — current state for debugging / UI
- `GET /healthz`, `GET /readyz`

### 7.4 Implementation order

1. **Empty graph with two stub nodes** to validate checkpointing + interrupts
2. **FastAPI server** with `/workflows` and `/resume`
3. **PM agent** as first real node
4. **Architect agent** + first interrupt (architecture approval)
5. **Engineer + QA + Reviewer** loop
6. **DevOps agent** + final approval + deployment

---

## 8. Per-Agent Specs

### 8.1 Common base

All agents share a base class that handles:
- LLM client setup (Anthropic, model configurable per agent)
- MCP toolkit loading from a list of MCP server URLs
- Langfuse tracing
- Postgres audit logging of every tool call
- Structured-output validation (Pydantic models)
- Retry on transient failures

### 8.2 PM Agent

| Attribute | Value |
|---|---|
| Trigger | Jira webhook (new ticket) or scheduled cron |
| Tools | Jira MCP, Confluence MCP, Slack MCP |
| LLM | `claude-sonnet-4-6` |
| Output | Structured requirements doc (markdown) attached to Jira ticket |

Responsibilities:
- Ingest stakeholder requests, decompose into structured tickets
- Maintain Jira state, post status updates
- Run a daily standup summary into Slack

### 8.3 Architect Agent

| Attribute | Value |
|---|---|
| Trigger | Jira ticket labeled `needs-design` (via RabbitMQ) |
| Tools | Confluence MCP, GitHub MCP (read-only), Qdrant RAG over ADRs |
| LLM | `claude-opus-4-7` |
| Output | ADR markdown + Mermaid diagram, posted to Confluence |

Output schema (strict JSON):
```json
{
  "adr_markdown": "...",
  "diagram_mermaid": "...",
  "alternatives_considered": ["..."],
  "risk_assessment": "..."
}
```

### 8.4 Engineer Agent

| Attribute | Value |
|---|---|
| Trigger | Approved ticket via RabbitMQ |
| Runtime | Kubernetes Job, sandboxed (gVisor or Kata) |
| Tools | GitHub MCP, filesystem MCP, code execution, Qdrant RAG over codebase |
| LLM | `claude-opus-4-7` (preferred; fall back to Sonnet for small tasks) |

**Strong recommendation:** wrap **Claude Code** running headless rather than building from scratch. Pass it the ticket + workspace; let it open the PR. The wrapper code (~300 LOC) handles repo cloning, PR opening, and result reporting back to the orchestrator.

The Engineer Agent must follow the Git Flow rules in §10.

### 8.5 QA Agent

| Attribute | Value |
|---|---|
| Trigger | PR opened/updated (GitHub webhook → RabbitMQ) |
| Tools | GitHub MCP, Playwright MCP, code execution |
| LLM | `claude-sonnet-4-6` |

Behavior on a PR:
1. Post `agent/qa-review` check status as `in_progress`
2. Clone PR branch into a sandboxed K8s Job workspace
3. Analyze diff to classify changed areas
4. Generate additional test cases targeting the change
5. Run existing + generated tests
6. Approve via PR Review API + post `success` check, OR request changes + post `failure` check
7. Use **both** the Reviews API (for CODEOWNERS) and Checks API (for required status checks)

### 8.6 Reviewer Agent

| Attribute | Value |
|---|---|
| Trigger | PR opened/updated, but only after QA agent has run |
| Tools | GitHub MCP (read), Qdrant RAG over codebase + ADRs + style guide |
| LLM | `claude-opus-4-7` |

Reviews for: correctness, architecture fit, security, error handling, testing, maintainability, performance.

Output schema (strict JSON):
```json
{
  "decision": "approve" | "request_changes" | "comment",
  "summary": "one paragraph",
  "inline_comments": [
    {"path": "...", "line": N, "body": "...",
     "severity": "blocking" | "nit" | "suggestion"}
  ],
  "concerns_for_human": ["concern 1", "concern 2"]
}
```

Strict on safety (security, bugs, missing tests, architecture violations → blocking).
Lenient on style (naming, suggestions → comment only, never block).

The `concerns_for_human` field is surfaced prominently in the human review request. This is the key division of labor.

### 8.7 DevOps Agent

| Attribute | Value |
|---|---|
| Trigger | Merged PR or alert from observability (RabbitMQ) |
| Tools | Kubernetes MCP (covers ArgoCD CRDs), Slack MCP, observability MCP |
| LLM | `claude-opus-4-7` |

Operates GitOps-style only. See §4.3.

Production deploys are **never** fully autonomous: production-touching CRs require human approval through the workflow. Staging is autonomous.

### 8.8 Reviewer-of-the-Reviewer (optional later phase)

For high-stakes paths only — a second LLM critic that re-checks the Reviewer Agent's decisions. Skip in v1.

---

## 9. Approval Service (Slack-based)

### 9.1 Why Slack first

Building a custom web UI is ~1500 LOC plus auth, deployment, maintenance. Slack interactive messages get 90% of value in ~400 LOC. Build a custom UI later only if needed (rich diff views, non-Slack users, audit reporting).

### 9.2 Architecture

```
LangGraph workflow ── reaches gate (interrupt) ──→ Approval Service
                                                         │
                                                         ▼
                                                 Slack channel (interactive message)
                                                         │
LangGraph workflow ←── /resume call ──── Approval ←── Button click
```

### 9.3 Endpoints

- `POST /approval-requests` — called by an orchestrator interrupt; posts an interactive Slack message
- `POST /slack/interactions` — receives Slack button clicks; verifies signature; calls orchestrator `/resume`
- `POST /slack/modal-submit` — receives "request changes" feedback modal submissions

### 9.4 Slack message structure

Always include:
- One-line summary of the agent's decision
- Direct link to the full artifact (Confluence, PR, ADR)
- 2–3 bullet points of reasoning
- Risk callouts
- Token cost
- Three buttons: Approve / Reject / Request Changes (opens modal for feedback)

### 9.5 Authorization

- **Slack signature verification** on every request
- **Approver allowlist** by role, looked up from IdP via SCIM data:

```python
APPROVER_ROLES = {
    "architecture": ["senior-eng", "tech-lead", "architect"],
    "deployment-staging": ["senior-eng", "tech-lead"],
    "deployment-production": ["tech-lead", "engineering-manager"],
}
```

### 9.6 Postgres schema

```sql
CREATE TABLE approval_requests (
    workflow_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    slack_channel TEXT NOT NULL,
    slack_message_ts TEXT NOT NULL,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    decision TEXT,
    approver TEXT,
    feedback TEXT
);
```

### 9.7 Channel routing

- `#agent-approvals-arch` — architecture approvals
- `#agent-approvals-prs` — final PR/merge approvals
- `#agent-approvals-prod` — production deployments
- `#agent-incidents` — DevOps agent escalations

---

## 10. Git Flow + PR Review Rules (Critical)

### 10.1 Branching model

Standard Git Flow:
- `main` (production)
- `develop` (integration)
- `feature/*` (agent or human work)
- `release/*` (release branches)
- `hotfix/*` (emergency fixes)

### 10.2 Review gate sequence on every feature → develop PR

```
PR opened
    ↓
[1] CI runs (build + tests + lint)         ← GitHub Actions
    ↓
[2] QA Agent reviews                        ← generates/runs tests
    ↓
[3] Reviewer Agent reviews                  ← code quality, arch, security
    ↓
[4] BOTH agents must approve               ← branch protection enforces
    ↓
[5] Human reviewer notified ONLY NOW       ← orchestrator posts to Slack
    ↓
[6] Human approves
    ↓
[7] Merge to develop
```

**A human is never asked to review until both agents have approved.** This is a hard constraint and is enforced by orchestrator logic, not just convention.

### 10.3 GitHub Apps (one identity per agent)

Create two GitHub Apps:
- `agent-qa-bot`
- `agent-reviewer-bot`

Each with permissions: Contents (read), Pull requests (write), Checks (write), Statuses (write). Subscribe to: pull request, pull request review, check suite events.

The Engineer Agent uses a third GitHub App identity (`agent-engineer-bot`) with Contents (write) for pushing to feature branches.

### 10.4 Branch protection on `develop`

```yaml
required_pull_request_reviews:
  required_approving_review_count: 2
  require_code_owner_reviews: true
  dismiss_stale_reviews: true             # New commits invalidate approvals
required_status_checks:
  strict: true
  contexts:
    - "ci/build"
    - "ci/tests"
    - "ci/lint"
    - "agent/qa-review"
    - "agent/code-review"
enforce_admins: false                      # Allow break-glass
```

### 10.5 CODEOWNERS

```
*                     @org/qa-bot @org/reviewer-bot @org/team-engineering
/services/auth/**     @org/qa-bot @org/reviewer-bot @org/team-security
/infra/**             @org/qa-bot @org/reviewer-bot @org/team-platform
/infra/production/**  @org/qa-bot @org/reviewer-bot @org/sre-leads
```

For `/infra/production/**`, use a GitHub Ruleset to require **3** approvals (1 agent + 2 humans).

### 10.6 Human notification flow

Orchestrator service `pr-orchestrator` listens to GitHub PR review events. Logic:

```python
async def on_pr_review_submitted(event):
    reviews = await github.list_pr_reviews(repo, pr_number)
    qa_approved = any(r.user == "qa-bot[bot]" and r.state == "APPROVED"
                      for r in reviews)
    reviewer_approved = any(r.user == "reviewer-bot[bot]" and r.state == "APPROVED"
                            for r in reviews)
    if qa_approved and reviewer_approved:
        reviewer = pick_human_reviewer(team_from_codeowners(pr), pr.author)
        await github.request_reviewers(repo, pr_number, [reviewer])
        await slack.post_review_request(reviewer, pr, agent_summaries=...)
```

Never request human review at PR open time — only after both agents approve.

### 10.7 Edge cases (must be handled)

**Engineer self-loop:** cap review cycles at 3. After 3, label the PR `needs-human-help` and escalate, bypassing the agent-first rule.

**Stale approvals on new commits:** handled automatically by `dismiss_stale_reviews: true`. Agents re-review on every push.

**Human override of agent rejection:** allow a `override-agent-review` label that, when applied by a senior engineer (verified via team membership), dismisses the agent's review. Implement via a small GitHub Action.

**Critical-path PRs:** more reviewers required via Rulesets on path patterns.

**Develop → main:** stricter rules. Two human approvals minimum. Agents post comments only, do not approve. This merge is consequential enough that humans drive it explicitly.

---

## 11. PR Orchestrator Service

Separate service from the LangGraph orchestrator (different lifecycle, different responsibilities).

### 11.1 Responsibilities

- Subscribe to GitHub webhooks: `pull_request`, `pull_request_review`, `check_suite`
- Verify webhook signatures
- Push relevant events to RabbitMQ topics that QA and Reviewer agents consume
- Detect "both agents approved" state and trigger human notification
- Handle the `override-agent-review` label workflow
- Track review cycle counts per PR (Postgres)
- Escalate stuck PRs

### 11.2 Endpoints

- `POST /github/webhook` — main webhook receiver
- `GET /pr-status/{repo}/{number}` — debug view of where a PR is in the gate flow
- `GET /healthz`, `GET /readyz`

### 11.3 Postgres schema

```sql
CREATE TABLE pr_state (
    repo TEXT NOT NULL,
    pr_number INT NOT NULL,
    head_sha TEXT NOT NULL,
    review_cycle_count INT DEFAULT 0,
    qa_decision TEXT,
    reviewer_decision TEXT,
    human_requested_at TIMESTAMPTZ,
    human_decision TEXT,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (repo, pr_number)
);

CREATE TABLE mcp_audit_log (
    id BIGSERIAL PRIMARY KEY,
    workflow_id TEXT,
    agent_name TEXT,
    tool TEXT,
    args JSONB,
    result JSONB,
    ts TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 12. Observability

- **Langfuse** for LLM tracing: every prompt, completion, tool call, cost
- **Prometheus + Grafana** for infrastructure (use the existing stack)
- **Loki** or existing log stack for application logs
- **Custom dashboards** in Grafana: agent throughput, approval gate latency, retry rates, cost per workflow run, human override rate per agent

Track these key metrics from day one:
- Time from ticket open to PR opened
- Time from PR opened to human review requested
- Agent approval rate (target: >70% first-pass)
- Human override rate of agent decisions (target: <10%)
- Cost per workflow run

---

## 13. Security & Guardrails

### 13.1 Identity

- Each agent runs under its own Kubernetes ServiceAccount
- Each agent has its own GitHub App / Atlassian / Slack identity
- All cross-service auth via short-lived tokens from External Secrets

### 13.2 Production safety

- DevOps Agent has no direct production write access — production CR changes always go through human-approval workflow
- ArgoCD RBAC further enforces this: agent service account cannot sync production projects
- Sandbox / staging projects: agent autonomy permitted

### 13.3 Code execution sandboxing

Engineer Agent and QA Agent run in K8s Jobs with:
- gVisor or Kata Containers runtime
- No outbound network except to required MCP servers and the package registry
- Resource limits, time limits (15 min default)
- Read-only root filesystem; tmpfs for workspace

### 13.4 Prompt injection defense

NeMo Guardrails sidecar on each agent:
- Input validators: PII detection, suspicious instruction patterns
- Output validators: schema conformance, policy compliance
- Tool use validators: refuse calls outside the agent's allowed tool set

### 13.5 Audit trail

Every tool call by every agent is logged to `mcp_audit_log` (workflow_id, agent, tool, args, result, timestamp). This is the forensics trail for any incident.

---

## 14. Implementation Roadmap

### Phase 1 — Foundation (Week 1–2)

1. Set up the monorepo and CI for the platform itself
2. Deploy RabbitMQ, Postgres (CloudNativePG), Qdrant, Langfuse, MinIO via ArgoCD
3. Set up External Secrets connected to your vault
4. Create LLM API keys, store via External Secrets
5. Stand up MCP servers for GitHub, Jira, Confluence, Kubernetes, Slack
6. Verify connectivity from a debug pod (MCP inspector)

### Phase 2 — Orchestrator skeleton (Week 3)

1. Empty LangGraph graph with two stub nodes; validate Postgres checkpointing
2. FastAPI server with `/workflows` and `/resume`
3. Add Langfuse tracing
4. Test interrupt + resume cycle end-to-end with curl

### Phase 3 — First two agents (Week 4)

1. Implement base agent class
2. PM agent — wired to Jira webhook, produces structured requirements doc
3. Architect agent — produces ADR + Mermaid diagram, posts to Confluence
4. First interrupt + Slack approval message via approval service
5. End-to-end test: Jira ticket → requirements → ADR → human approval

### Phase 4 — Engineer loop with PR gates (Week 5–6)

1. GitHub Apps created and installed (`agent-engineer-bot`, `agent-qa-bot`, `agent-reviewer-bot`)
2. Branch protection rules + CODEOWNERS configured
3. Engineer agent (wrapping Claude Code headless)
4. QA agent — reviews PRs via webhook trigger
5. Reviewer agent — reviews PRs via webhook trigger
6. PR orchestrator service — handles webhook routing + cycle counting
7. Human notification flow (Slack ping after both agents approve)
8. End-to-end test: Jira ticket → PR opened → both agents approve → human approves → merge

### Phase 5 — DevOps + production rollout (Week 7–8)

1. DevOps agent operating via Kubernetes MCP / GitOps
2. Final approval gate before deploy
3. Deployment monitoring loop
4. Incident response webhook integration
5. Run on a single sandbox repo with willing volunteers
6. Shadow mode first (agents comment, don't approve), then full mode

### Phase 6 — Hardening (Week 9+)

- Tune agent prompts based on observed false positives/negatives
- Build feedback loop where humans can mark agent reviews as agreed/disagreed
- Roll out to additional repos
- Add reviewer-of-the-reviewer for high-stakes paths
- Custom approval UI (only if Slack proves insufficient)

---

## 15. Critical Calibration Note

The Reviewer Agent's quality is the linchpin of this system. If it approves bad code, humans lose trust and start scrutinizing every PR (defeating the purpose). If it rejects too aggressively, engineers get frustrated and ignore it.

Investment areas:
- **Calibration corpus** — at least 50 historical PRs labeled with what humans actually decided, used as evaluation set
- **Coding standards in context** — RAG over the team's style guide, ADRs, security policies
- **Agreement metric tracked over time** — humans mark agent reviews as agreed/disagreed; aim for >90% on safety calls

Reviewer agent at 90% agreement = genuinely useful. At 70% = net negative. Treat its calibration as ongoing, not one-time setup.

---

## 16. Decisions Log

Track architectural decisions made during implementation here. Format: date, decision, rationale.

- **2026-04-26** — No custom ArgoCD MCP server; Kubernetes MCP server suffices (ArgoCD state is CRDs).
- **2026-04-26** — Approval UI: Slack-first, custom web UI deferred.
- **2026-04-26** — Engineer Agent wraps Claude Code headless rather than building from scratch.
- **2026-04-26** — Two-agent + one-human review on every feature→develop PR; humans only pinged after both agents approve.
- **2026-04-26** — develop→main: agents comment only, two human approvals required.

---

## 17. Open Questions for the Team

These need decisions before / during implementation:

1. Which LLM provider for embeddings? (Voyage vs OpenAI vs self-hosted)
2. Which observability stack already in use? (Datadog vs Prometheus/Grafana/Loki)
3. Which IdP provides role lookup for approval authorization? (Okta? Entra ID?)
4. Sandboxed runtime preference — gVisor or Kata Containers?
5. RabbitMQ vs Kafka — does the org already run one at scale?
6. Initial sandbox repo for Phase 5 rollout — which team/repo?
7. Production deployment policy — fully gated by human or only certain paths?

---

## 18. Conventions for Claude Code (When Implementing)

- **Language:** Python 3.12 for all services. Type hints required (`mypy --strict`).
- **Framework:** FastAPI for HTTP services. LangGraph for orchestration.
- **Testing:** `pytest` with `pytest-asyncio`. Every non-trivial piece of code **must** have unit tests — this is non-negotiable. "Non-trivial" means anything beyond pure data declarations (Pydantic models, TypedDicts, settings classes) and single-line configuration. Concretely: all routing functions, all parsing/extraction helpers, all HTTP endpoints (including error paths), all business-logic functions in service handlers, and all stateful node logic must be covered. Aim for ≥80% line coverage on agent logic and service handlers; pure config/schema files are exempt. Test files live next to the code they test (`<package>/tests/`). When adding a feature, write the tests in the same PR.
- **Linting:** `ruff` (formatter + linter). `mypy` in CI.
- **Dependency management:** `uv` for speed.
- **Containers:** Multi-stage Dockerfiles, distroless runtime image, non-root user.
- **Logging:** Structured JSON logs to stdout. Use `structlog`.
- **Config:** Pydantic Settings, env-var driven. No config files in containers.
- **Secrets:** Always via External Secrets → mounted env vars. Never in code or git.
- **Commits:** Conventional Commits. PRs must reference a Jira ticket.
- **No comments explaining what the code does** — code should be self-documenting. Comments only for *why*, not *what*.
- **PR monitoring:** After opening a PR or pushing to an existing one, always call `subscribe_pr_activity` for that PR. Automatically address any review comments or CI failures that arrive as `<github-webhook-activity>` events: fix and push if the change is clear and small; ask the author first if it is ambiguous or architecturally significant; reply with an explanation if no code change is needed.

When implementing a component, follow this order: types/schemas → tests (red) → implementation (green) → integration test → docs update.

---

## 19. How to Use This Document

When implementing any component, first re-read the relevant section here. If a decision is ambiguous or contradicted by reality during implementation, **update this file in the same PR** that changes the implementation. The doc and the code stay in lockstep.

Update §16 (Decisions Log) for any new architectural choice.
