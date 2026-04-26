import json
from typing import Any

import structlog
from agents_base.agent import BaseAgent

from ..state import ProjectState

log = structlog.get_logger()


async def architect_node(state: ProjectState) -> dict[str, Any]:
    log.info("architect_node.start", ticket=state["jira_ticket_id"])
    agent = BaseAgent(
        name="architect",
        mcp_servers=["confluence", "github", "qdrant"],
        model="claude-opus-4-7",
        workflow_run_id=state["workflow_run_id"],
    )
    result = await agent.run(
        system=_SYSTEM_PROMPT,
        user=(
            f"Design the architecture for:\n\n{state.get('requirements_doc', '')}\n\n"
            f"Repo: {state['github_repo']}. "
            "Return JSON matching the required output schema."
        ),
    )
    try:
        decision = json.loads(result.text)
    except json.JSONDecodeError:
        decision = {
            "adr_markdown": result.text,
            "diagram_mermaid": "",
            "alternatives_considered": [],
            "risk_assessment": "",
        }

    log.info("architect_node.done", ticket=state["jira_ticket_id"])
    return {
        "architecture_decision": json.dumps(decision),
        "current_phase": "design",
        "approval_required": True,
    }


_SYSTEM_PROMPT = """\
You are the Architect Agent. You produce Architecture Decision Records (ADRs) and Mermaid diagrams.

Always query Qdrant for existing ADRs before proposing a design. Check Confluence for relevant
existing docs. Use GitHub (read-only) to understand current codebase structure.

Return ONLY valid JSON matching this schema exactly:
{
  "adr_markdown": "<full ADR in Markdown>",
  "diagram_mermaid": "<Mermaid diagram string>",
  "alternatives_considered": ["<alt 1>", "<alt 2>"],
  "risk_assessment": "<paragraph>"
}

Post the ADR to Confluence after generating it.
"""
