from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_start_workflow(mock_graph):
    import orchestrator.server as srv

    srv._graph = mock_graph
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/workflows", json={"jira_ticket_id": "PROJ-1", "github_repo": "org/repo"}
        )
    assert resp.status_code == 201
    assert "workflow_run_id" in resp.json()
