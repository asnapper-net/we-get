import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.nodes.engineer import _extract_pr_url
from orchestrator.nodes.gates import await_arch_approval_node, await_pr_approval_node, fail_node
from orchestrator.nodes.qa import _parse_qa_result
from orchestrator.nodes.reviewer import _parse_review

# ---------------------------------------------------------------------------
# _extract_pr_url
# ---------------------------------------------------------------------------


def test_extract_pr_url_found() -> None:
    text = "Done! PR at https://github.com/org/repo/pull/42 — please review."
    assert _extract_pr_url(text) == "https://github.com/org/repo/pull/42"


def test_extract_pr_url_not_found_returns_stripped_text() -> None:
    assert _extract_pr_url("  no url here  ") == "no url here"


def test_extract_pr_url_ignores_non_pr_github_urls() -> None:
    text = "See https://github.com/org/repo/issues/1 for context"
    assert _extract_pr_url(text) == text.strip()


# ---------------------------------------------------------------------------
# _parse_qa_result
# ---------------------------------------------------------------------------


def test_parse_qa_result_valid_json_embedded() -> None:
    text = 'Prefix {"failed": false, "summary": "ok", "test_cases_added": 2, "failures": []} suffix'
    result = _parse_qa_result(text)
    assert result["failed"] is False
    assert result["summary"] == "ok"
    assert result["test_cases_added"] == 2


def test_parse_qa_result_failed_true_in_json() -> None:
    text = '{"failed": true, "summary": "broke", "failures": ["test_foo"]}'
    result = _parse_qa_result(text)
    assert result["failed"] is True


def test_parse_qa_result_no_json_all_pass() -> None:
    result = _parse_qa_result("All tests passed successfully.")
    assert result["failed"] is False


def test_parse_qa_result_fail_keyword_detected() -> None:
    result = _parse_qa_result("There was a FAIL in test_something.")
    assert result["failed"] is True


def test_parse_qa_result_error_keyword_detected() -> None:
    result = _parse_qa_result("Encountered an error during execution.")
    assert result["failed"] is True


def test_parse_qa_result_broken_keyword_detected() -> None:
    result = _parse_qa_result("The pipeline is broken.")
    assert result["failed"] is True


def test_parse_qa_result_missing_test_keyword_detected() -> None:
    result = _parse_qa_result("missing test coverage for auth module")
    assert result["failed"] is True


def test_parse_qa_result_malformed_json_falls_back() -> None:
    result = _parse_qa_result("some { not valid json } here")
    assert "failed" in result
    assert "summary" in result


# ---------------------------------------------------------------------------
# _parse_review
# ---------------------------------------------------------------------------


def test_parse_review_valid_json_approve() -> None:
    text = '{"decision":"approve","summary":"lgtm","inline_comments":[],"concerns_for_human":[]}'
    result = _parse_review(text)
    assert result["decision"] == "approve"
    assert result["summary"] == "lgtm"
    assert result["inline_comments"] == []


def test_parse_review_valid_json_request_changes() -> None:
    text = (
        '{"decision": "request_changes", "summary": "fix it",'
        ' "inline_comments": [], "concerns_for_human": ["security risk"]}'
    )
    result = _parse_review(text)
    assert result["decision"] == "request_changes"
    assert result["concerns_for_human"] == ["security risk"]


def test_parse_review_no_json_returns_comment_fallback() -> None:
    result = _parse_review("Looks fine to me overall.")
    assert result["decision"] == "comment"
    assert result["summary"] == "Looks fine to me overall."
    assert result["inline_comments"] == []
    assert result["concerns_for_human"] == []


def test_parse_review_malformed_json_returns_fallback() -> None:
    result = _parse_review("{ not valid json }")
    assert result["decision"] == "comment"


# ---------------------------------------------------------------------------
# Gate nodes
# ---------------------------------------------------------------------------


async def test_await_arch_approval_node_clears_approval_required() -> None:
    result = await await_arch_approval_node({})  # type: ignore[arg-type]
    assert result["current_phase"] == "design"
    assert result["approval_required"] is False


async def test_await_pr_approval_node_clears_approval_required() -> None:
    result = await await_pr_approval_node({})  # type: ignore[arg-type]
    assert result["current_phase"] == "review"
    assert result["approval_required"] is False


async def test_fail_node_sets_failed_phase() -> None:
    result = await fail_node({})  # type: ignore[arg-type]
    assert result["current_phase"] == "failed"


# ---------------------------------------------------------------------------
# pm_node
# ---------------------------------------------------------------------------


def _base_state(**overrides: Any) -> Any:
    state: dict[str, Any] = {
        "jira_ticket_id": "PROJ-1",
        "github_repo": "org/repo",
        "workflow_run_id": "run-1",
        "requirements_doc": None,
        "architecture_decision": None,
        "pr_url": None,
        "test_results": None,
        "deployment_status": None,
        "current_phase": "intake",
        "approval_required": False,
        "approval_granted": None,
        "messages": [],
        "errors": [],
        "retry_count": 0,
    }
    state.update(overrides)
    return state


async def test_pm_node_returns_requirements_doc() -> None:
    from orchestrator.nodes.pm import pm_node

    mock_result = MagicMock(text="## Summary\n- Do the thing")
    with patch("orchestrator.nodes.pm.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await pm_node(_base_state())

    assert result["requirements_doc"] == "## Summary\n- Do the thing"
    assert result["current_phase"] == "intake"


async def test_pm_node_instantiates_agent_with_correct_servers() -> None:
    from orchestrator.nodes.pm import pm_node

    mock_result = MagicMock(text="requirements")
    with patch("orchestrator.nodes.pm.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        await pm_node(_base_state())

    _, kwargs = mock_cls.call_args
    assert set(kwargs["mcp_servers"]) == {"jira", "confluence", "slack"}
    assert kwargs["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# architect_node
# ---------------------------------------------------------------------------


async def test_architect_node_parses_valid_json() -> None:
    from orchestrator.nodes.architect import architect_node

    payload = {
        "adr_markdown": "# ADR",
        "diagram_mermaid": "graph TD",
        "alternatives_considered": [],
        "risk_assessment": "low",
    }
    mock_result = MagicMock(text=json.dumps(payload))
    with patch("orchestrator.nodes.architect.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await architect_node(_base_state(requirements_doc="Build X"))

    decision = json.loads(result["architecture_decision"])
    assert decision["adr_markdown"] == "# ADR"
    assert result["approval_required"] is True
    assert result["current_phase"] == "design"


async def test_architect_node_falls_back_on_invalid_json() -> None:
    from orchestrator.nodes.architect import architect_node

    mock_result = MagicMock(text="Plain text ADR — not JSON at all.")
    with patch("orchestrator.nodes.architect.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await architect_node(_base_state())

    decision = json.loads(result["architecture_decision"])
    assert decision["adr_markdown"] == "Plain text ADR — not JSON at all."
    assert decision["diagram_mermaid"] == ""
    assert decision["alternatives_considered"] == []


# ---------------------------------------------------------------------------
# engineer_node
# ---------------------------------------------------------------------------


async def test_engineer_node_extracts_pr_url() -> None:
    from orchestrator.nodes.engineer import engineer_node

    mock_result = MagicMock(text="Opened https://github.com/org/repo/pull/7")
    with patch("orchestrator.nodes.engineer.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await engineer_node(_base_state())

    assert result["pr_url"] == "https://github.com/org/repo/pull/7"
    assert result["current_phase"] == "implementation"


async def test_engineer_node_preserves_retry_count() -> None:
    from orchestrator.nodes.engineer import engineer_node

    mock_result = MagicMock(text="https://github.com/org/repo/pull/8")
    with patch("orchestrator.nodes.engineer.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await engineer_node(_base_state(retry_count=2))

    assert result["retry_count"] == 2


async def test_engineer_node_includes_feedback_in_context_when_present() -> None:
    from orchestrator.nodes.engineer import engineer_node

    mock_result = MagicMock(text="https://github.com/org/repo/pull/9")
    feedback = {"failed": True, "summary": "missing tests"}
    with patch("orchestrator.nodes.engineer.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        await engineer_node(_base_state(test_results=feedback))

    _, call_kwargs = mock_cls.return_value.run.call_args
    assert str(feedback) in call_kwargs["user"]


# ---------------------------------------------------------------------------
# qa_node
# ---------------------------------------------------------------------------


async def test_qa_node_returns_parsed_test_results() -> None:
    from orchestrator.nodes.qa import qa_node

    qa_json = '{"failed": false, "summary": "all pass", "test_cases_added": 3, "failures": []}'
    mock_result = MagicMock(text=qa_json)
    with patch("orchestrator.nodes.qa.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await qa_node(_base_state(pr_url="https://github.com/org/repo/pull/1"))

    assert result["test_results"]["failed"] is False
    assert result["test_results"]["test_cases_added"] == 3


# ---------------------------------------------------------------------------
# reviewer_node
# ---------------------------------------------------------------------------


async def test_reviewer_node_increments_retry_count_on_issues() -> None:
    from orchestrator.nodes.reviewer import reviewer_node

    review_json = (
        '{"decision": "request_changes", "summary": "fix security issue",'
        ' "inline_comments": [], "concerns_for_human": ["SQL injection risk"]}'
    )
    mock_result = MagicMock(text=review_json)
    with patch("orchestrator.nodes.reviewer.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await reviewer_node(_base_state(retry_count=1))

    assert result["retry_count"] == 2
    assert result["test_results"]["review_issues"] is True
    assert result["test_results"]["concerns_for_human"] == ["SQL injection risk"]


async def test_reviewer_node_does_not_increment_retry_on_approve() -> None:
    from orchestrator.nodes.reviewer import reviewer_node

    review_json = (
        '{"decision": "approve", "summary": "lgtm",'
        ' "inline_comments": [], "concerns_for_human": []}'
    )
    mock_result = MagicMock(text=review_json)
    with patch("orchestrator.nodes.reviewer.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await reviewer_node(_base_state(retry_count=1))

    assert result["retry_count"] == 1
    assert result["test_results"]["review_issues"] is False


async def test_reviewer_node_merges_existing_test_results() -> None:
    from orchestrator.nodes.reviewer import reviewer_node

    review_json = (
        '{"decision": "approve", "summary": "ok", "inline_comments": [], "concerns_for_human": []}'
    )
    mock_result = MagicMock(text=review_json)
    existing = {"failed": False, "test_cases_added": 5}
    with patch("orchestrator.nodes.reviewer.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await reviewer_node(_base_state(test_results=existing))

    assert result["test_results"]["test_cases_added"] == 5
    assert "reviewer_summary" in result["test_results"]


# ---------------------------------------------------------------------------
# devops_node
# ---------------------------------------------------------------------------


async def test_devops_node_returns_done_phase() -> None:
    from orchestrator.nodes.devops import devops_node

    mock_result = MagicMock(text="Deployed to staging. ArgoCD sync complete.")
    with patch("orchestrator.nodes.devops.BaseAgent") as mock_cls:
        mock_cls.return_value.run = AsyncMock(return_value=mock_result)
        result = await devops_node(_base_state(pr_url="https://github.com/org/repo/pull/1"))

    assert result["current_phase"] == "done"
    assert result["deployment_status"] == "Deployed to staging. ArgoCD sync complete."
