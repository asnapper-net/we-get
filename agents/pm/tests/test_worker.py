import json
from unittest.mock import AsyncMock, MagicMock, patch

from pm.worker import handle_ticket


def _make_message(body: dict) -> MagicMock:
    msg = MagicMock()
    msg.body = json.dumps(body).encode()
    process_cm = AsyncMock()
    process_cm.__aenter__ = AsyncMock(return_value=None)
    process_cm.__aexit__ = AsyncMock(return_value=False)
    msg.process = MagicMock(return_value=process_cm)
    return msg


def _make_http_client(status_code: int = 201) -> tuple[MagicMock, MagicMock]:
    mock_resp = MagicMock(status_code=status_code)
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_cls = MagicMock(return_value=mock_http)
    return mock_cls, mock_http


async def test_handle_ticket_posts_to_orchestrator() -> None:
    message = _make_message({"issue": {"key": "PROJ-42"}, "github_repo": "org/my-repo"})
    mock_cls, mock_http = _make_http_client()

    with patch("pm.worker.httpx.AsyncClient", mock_cls):
        await handle_ticket(message)

    mock_http.post.assert_called_once()
    _, call_kwargs = mock_http.post.call_args
    assert call_kwargs["json"]["jira_ticket_id"] == "PROJ-42"
    assert call_kwargs["json"]["github_repo"] == "org/my-repo"


async def test_handle_ticket_skips_when_ticket_id_missing() -> None:
    message = _make_message({"issue": {}, "github_repo": "org/repo"})
    mock_cls, mock_http = _make_http_client()

    with patch("pm.worker.httpx.AsyncClient", mock_cls):
        await handle_ticket(message)

    mock_http.post.assert_not_called()


async def test_handle_ticket_skips_when_github_repo_missing() -> None:
    message = _make_message({"issue": {"key": "PROJ-1"}})
    mock_cls, mock_http = _make_http_client()

    with patch("pm.worker.httpx.AsyncClient", mock_cls):
        await handle_ticket(message)

    mock_http.post.assert_not_called()


async def test_handle_ticket_skips_when_both_fields_missing() -> None:
    message = _make_message({})
    mock_cls, mock_http = _make_http_client()

    with patch("pm.worker.httpx.AsyncClient", mock_cls):
        await handle_ticket(message)

    mock_http.post.assert_not_called()
