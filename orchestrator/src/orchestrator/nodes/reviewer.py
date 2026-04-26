import json
import re
from typing import Any

import structlog
from agents_base.agent import BaseAgent

from ..state import ProjectState

log = structlog.get_logger()


async def reviewer_node(state: ProjectState) -> dict[str, Any]:
    log.info("reviewer_node.start", pr_url=state.get("pr_url"))
    agent = BaseAgent(
        name="reviewer",
        mcp_servers=["github", "qdrant"],
        model="claude-opus-4-7",
        workflow_run_id=state["workflow_run_id"],
    )
    result = await agent.run(
        system=_SYSTEM_PROMPT,
        user=(
            f"Review PR: {state.get('pr_url')}\n"
            f"Repo: {state['github_repo']}\n"
            f"Architecture decision:\n{state.get('architecture_decision', '')}"
        ),
    )
    review = _parse_review(result.text)
    has_issues = review.get("decision") == "request_changes"
    log.info("reviewer_node.done", decision=review.get("decision"))

    test_results: dict[str, Any] = dict(state.get("test_results") or {})
    test_results["review_issues"] = has_issues
    test_results["reviewer_summary"] = review.get("summary", "")
    test_results["concerns_for_human"] = review.get("concerns_for_human", [])

    return {
        "test_results": test_results,
        "retry_count": state.get("retry_count", 0) + (1 if has_issues else 0),
    }


def _parse_review(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass
    return {
        "decision": "comment",
        "summary": text,
        "inline_comments": [],
        "concerns_for_human": [],
    }


_SYSTEM_PROMPT = """\
You are the Reviewer Agent. You perform code reviews for correctness, architecture fit,
security, error handling, testing, maintainability, and performance.

Use Qdrant RAG to search for relevant ADRs, the style guide, and codebase context before reviewing.

Rules:
- Blocking: security issues, bugs, missing tests, architecture violations.
- Non-blocking (comment only): naming, suggestions, style.
- Never block on subjective style preferences.

Return ONLY valid JSON matching this schema:
{
  "decision": "approve" | "request_changes" | "comment",
  "summary": "<one paragraph>",
  "inline_comments": [
    {"path": "<file>", "line": <int>, "body": "<text>",
     "severity": "blocking" | "nit" | "suggestion"}
  ],
  "concerns_for_human": ["<concern 1>"]
}

Post the review to the PR via GitHub MCP.
"""
