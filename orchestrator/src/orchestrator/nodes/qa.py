import json
import re
from typing import Any

import structlog
from agents_base.agent import BaseAgent

from ..state import ProjectState

log = structlog.get_logger()


async def qa_node(state: ProjectState) -> dict[str, Any]:
    log.info("qa_node.start", pr_url=state.get("pr_url"))
    agent = BaseAgent(
        name="qa",
        mcp_servers=["github", "playwright"],
        model="claude-sonnet-4-6",
        workflow_run_id=state["workflow_run_id"],
    )
    result = await agent.run(
        system=_SYSTEM_PROMPT,
        user=(
            f"Review PR: {state.get('pr_url')}\n"
            f"Repo: {state['github_repo']}\n"
            f"Requirements:\n{state.get('requirements_doc', '')}"
        ),
    )
    test_results = _parse_qa_result(result.text)
    log.info("qa_node.done", failed=test_results.get("failed"))
    return {"test_results": test_results}


def _parse_qa_result(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass
    failed = any(kw in text.lower() for kw in ("fail", "error", "broken", "missing test"))
    return {"failed": failed, "summary": text}


_SYSTEM_PROMPT = """\
You are the QA Agent. You review pull requests by generating and running tests.

Steps:
1. Post agent/qa-review check as in_progress.
2. Analyze the PR diff to classify changed areas.
3. Generate additional test cases targeting the changes.
4. Run existing + generated tests.
5. If all pass: approve the PR and post check success.
   If any fail: request changes and post check failure.

Return JSON:
{
  "failed": <bool>,
  "summary": "<one paragraph>",
  "test_cases_added": <int>,
  "failures": ["<desc>"]
}
"""
