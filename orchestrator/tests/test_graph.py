from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from orchestrator.graph import build_graph
from orchestrator.state import ProjectState


@pytest.fixture
def graph():
    return build_graph(MemorySaver())


@pytest.fixture
def base_state() -> ProjectState:
    return {
        "jira_ticket_id": "PROJ-1",
        "github_repo": "org/repo",
        "workflow_run_id": "test-run-1",
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


@pytest.mark.asyncio
async def test_graph_interrupts_at_arch_approval(graph, base_state):
    config = {"configurable": {"thread_id": "test-1"}}

    with (
        patch("orchestrator.nodes.pm.BaseAgent") as mock_pm,
        patch("orchestrator.nodes.architect.BaseAgent") as mock_arch,
    ):
        mock_pm.return_value.run = AsyncMock(
            return_value=AsyncMock(text="# Requirements\n- Do the thing")
        )
        mock_arch.return_value.run = AsyncMock(
            return_value=AsyncMock(
                text=(
                    '{"adr_markdown":"# ADR","diagram_mermaid":"graph TD",'
                    '"alternatives_considered":[],"risk_assessment":"low"}'
                )
            )
        )
        await graph.ainvoke(base_state, config)

    snapshot = await graph.aget_state(config)
    assert snapshot is not None
    assert "await_arch_approval" in list(snapshot.next or [])


@pytest.mark.asyncio
async def test_resume_arch_approval_proceeds_to_engineer(graph, base_state):
    config = {"configurable": {"thread_id": "test-2"}}

    with (
        patch("orchestrator.nodes.pm.BaseAgent") as mock_pm,
        patch("orchestrator.nodes.architect.BaseAgent") as mock_arch,
        patch("orchestrator.nodes.engineer.BaseAgent") as mock_eng,
    ):
        mock_pm.return_value.run = AsyncMock(return_value=AsyncMock(text="requirements"))
        mock_arch.return_value.run = AsyncMock(
            return_value=AsyncMock(
                text=(
                    '{"adr_markdown":"ADR","diagram_mermaid":"",'
                    '"alternatives_considered":[],"risk_assessment":""}'
                )
            )
        )
        mock_eng.return_value.run = AsyncMock(
            return_value=AsyncMock(text="https://github.com/org/repo/pull/1")
        )
        await graph.ainvoke(base_state, config)

        await graph.aupdate_state(config, {"approval_granted": True, "approval_required": False})
        with (
            patch("orchestrator.nodes.qa.BaseAgent") as mock_qa,
            patch("orchestrator.nodes.reviewer.BaseAgent") as mock_rev,
        ):
            mock_qa.return_value.run = AsyncMock(
                return_value=AsyncMock(
                    text=(
                        '{"failed": false, "summary": "all pass",'
                        ' "test_cases_added": 2, "failures": []}'
                    )
                )
            )
            mock_rev.return_value.run = AsyncMock(
                return_value=AsyncMock(
                    text=(
                        '{"decision": "approve", "summary": "lgtm",'
                        ' "inline_comments": [], "concerns_for_human": []}'
                    )
                )
            )
            await graph.ainvoke(None, config)

    snapshot = await graph.aget_state(config)
    assert snapshot is not None
    assert "await_pr_approval" in list(snapshot.next or [])
