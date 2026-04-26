from typing import Any

import structlog
from agents_base.agent import BaseAgent

from ..state import ProjectState

log = structlog.get_logger()


async def devops_node(state: ProjectState) -> dict[str, Any]:
    log.info("devops_node.start", pr_url=state.get("pr_url"))
    agent = BaseAgent(
        name="devops",
        mcp_servers=["kubernetes", "slack"],
        model="claude-opus-4-7",
        workflow_run_id=state["workflow_run_id"],
    )
    result = await agent.run(
        system=_SYSTEM_PROMPT,
        user=(
            f"Deploy the merged PR to staging.\n"
            f"Repo: {state['github_repo']}\n"
            f"PR: {state.get('pr_url')}\n"
            "Report deployment status."
        ),
    )
    log.info("devops_node.done")
    return {
        "deployment_status": result.text,
        "current_phase": "done",
    }


_SYSTEM_PROMPT = """\
You are the DevOps Agent. You operate exclusively via GitOps using the Kubernetes MCP server.

Mental model: To deploy, modify the ArgoCD Application CR's targetRevision field to the desired
git SHA — never run imperative argocd commands. The CR is the source of truth.

Operations:
- Deploy to staging: patch Application CR targetRevision, then trigger sync by patching
  the operation field.
- Rollback: patch targetRevision back to the previous SHA.
- Refresh: set the argocd.argoproj.io/refresh annotation.
- Monitor: watch Application CR status.sync.status and status.health.status.

Production deploys always require human approval and are never autonomous.
Report progress and final status to the #agent-incidents Slack channel.
"""
