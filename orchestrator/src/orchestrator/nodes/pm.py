from typing import Any

import structlog
from agents_base.agent import BaseAgent

from ..state import ProjectState

log = structlog.get_logger()


async def pm_node(state: ProjectState) -> dict[str, Any]:
    log.info("pm_node.start", ticket=state["jira_ticket_id"])
    agent = BaseAgent(
        name="pm",
        mcp_servers=["jira", "confluence", "slack"],
        model="claude-sonnet-4-6",
        workflow_run_id=state["workflow_run_id"],
    )
    result = await agent.run(
        system=_SYSTEM_PROMPT,
        user=(
            f"Process Jira ticket {state['jira_ticket_id']} in repo {state['github_repo']}. "
            "Produce a structured requirements document in Markdown."
        ),
    )
    log.info("pm_node.done", ticket=state["jira_ticket_id"])
    return {
        "requirements_doc": result.text,
        "current_phase": "intake",
    }


_SYSTEM_PROMPT = """\
You are the PM Agent. Your job is to ingest stakeholder requests from Jira, decompose them into
structured requirements, and maintain Jira ticket state.

Output a single Markdown document with these sections:
- ## Summary (one paragraph)
- ## Acceptance Criteria (checklist)
- ## Out of Scope
- ## Open Questions

Always attach the document to the Jira ticket via the Jira MCP tool when done.
"""
