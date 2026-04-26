import re
from typing import Any

import structlog
from agents_base.agent import BaseAgent

from ..state import ProjectState

log = structlog.get_logger()


async def engineer_node(state: ProjectState) -> dict[str, Any]:
    log.info(
        "engineer_node.start",
        ticket=state["jira_ticket_id"],
        cycle=state.get("retry_count", 0),
    )
    agent = BaseAgent(
        name="engineer",
        mcp_servers=["github", "filesystem", "qdrant"],
        model="claude-opus-4-7",
        workflow_run_id=state["workflow_run_id"],
    )

    context = (
        f"Ticket: {state['jira_ticket_id']}\n"
        f"Repo: {state['github_repo']}\n\n"
        f"Requirements:\n{state.get('requirements_doc', '')}\n\n"
        f"Architecture decision:\n{state.get('architecture_decision', '')}\n\n"
    )
    if state.get("test_results"):
        context += f"Previous review feedback:\n{state['test_results']}\n\n"

    result = await agent.run(
        system=_SYSTEM_PROMPT,
        user=context + "Implement the feature and open a pull request. Return the PR URL.",
    )

    pr_url = _extract_pr_url(result.text)
    log.info("engineer_node.done", ticket=state["jira_ticket_id"], pr_url=pr_url)
    return {
        "pr_url": pr_url,
        "current_phase": "implementation",
        "retry_count": state.get("retry_count", 0),
    }


def _extract_pr_url(text: str) -> str:
    match = re.search(r"https://github\.com/[^\s]+/pull/\d+", text)
    return match.group(0) if match else text.strip()


_SYSTEM_PROMPT = """\
You are the Engineer Agent. You implement features by wrapping Claude Code headless.

Workflow:
1. Clone or checkout the repo on a feature/* branch following Git Flow.
2. Implement the feature per the requirements and architecture decision.
3. Write or update tests.
4. Push the branch and open a PR against develop.
5. Return the PR URL.

Use the Qdrant RAG tool to search the codebase before writing code.
Follow existing conventions. Never commit secrets. Keep commits atomic.
"""
