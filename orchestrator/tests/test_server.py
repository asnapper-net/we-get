from unittest.mock import AsyncMock, MagicMock

import orchestrator.server as srv
import pytest
from httpx import ASGITransport, AsyncClient
from orchestrator.server import app


@pytest.fixture
def mock_graph():
    g = MagicMock()
    g.ainvoke = AsyncMock(return_value={})
    g.aupdate_state = AsyncMock()
    g.aget_state = AsyncMock(return_value=MagicMock(values={"current_phase": "intake"}))
    return g


@pytest.fixture(autouse=True)
def reset_graph(mock_graph):
    srv._graph = mock_graph
    yield
    srv._graph = None


async def test_healthz() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200


async def test_readyz_when_graph_initialized() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_when_graph_not_initialized() -> None:
    srv._graph = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 503


async def test_start_workflow_returns_run_id(mock_graph: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/workflows", json={"jira_ticket_id": "PROJ-1", "github_repo": "org/repo"}
        )
    assert resp.status_code == 201
    body = resp.json()
    assert "workflow_run_id" in body
    assert len(body["workflow_run_id"]) == 36  # UUID format


async def test_start_workflow_invokes_graph_with_initial_state(mock_graph: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/workflows", json={"jira_ticket_id": "PROJ-99", "github_repo": "acme/svc"}
        )
    mock_graph.ainvoke.assert_called_once()
    state = mock_graph.ainvoke.call_args[0][0]
    assert state["jira_ticket_id"] == "PROJ-99"
    assert state["github_repo"] == "acme/svc"
    assert state["current_phase"] == "intake"
    assert state["retry_count"] == 0


async def test_resume_workflow_approved(mock_graph: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/workflows/run-abc/resume",
            json={"approval_granted": True, "feedback": ""},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["workflow_id"] == "run-abc"
    assert body["resumed"] is True

    mock_graph.aupdate_state.assert_called_once()
    update = mock_graph.aupdate_state.call_args[0][1]
    assert update["approval_granted"] is True
    assert update["approval_required"] is False


async def test_resume_workflow_with_feedback_adds_errors(mock_graph: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/workflows/run-abc/resume",
            json={"approval_granted": False, "feedback": "needs security review"},
        )
    update = mock_graph.aupdate_state.call_args[0][1]
    assert update["errors"] == ["needs security review"]


async def test_get_workflow_returns_state(mock_graph: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/workflows/run-xyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workflow_id"] == "run-xyz"
    assert "state" in body


async def test_get_workflow_not_found(mock_graph: MagicMock) -> None:
    mock_graph.aget_state = AsyncMock(return_value=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/workflows/missing-id")
    assert resp.status_code == 404
