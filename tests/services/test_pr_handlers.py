from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helper: build a psycopg connection mock that works with
#   async with await psycopg.AsyncConnection.connect(...) as conn:
# ---------------------------------------------------------------------------


def _mock_conn(fetchone_result=None):
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=fetchone_result)
    conn.execute.return_value = cursor
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# _record_agent_review — column selection based on bot name
# ---------------------------------------------------------------------------


async def test_record_agent_review_qa_bot_updates_qa_decision() -> None:
    from pr_orchestrator.handlers import _record_agent_review

    conn = _mock_conn()
    with patch(
        "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
    ):
        await _record_agent_review("org/repo", 1, "agent-qa-bot[bot]", "APPROVED")

    sql = conn.execute.call_args[0][0]
    assert "qa_decision" in sql


async def test_record_agent_review_reviewer_bot_updates_reviewer_decision() -> None:
    from pr_orchestrator.handlers import _record_agent_review

    conn = _mock_conn()
    with patch(
        "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
    ):
        await _record_agent_review("org/repo", 1, "agent-reviewer-bot[bot]", "APPROVED")

    sql = conn.execute.call_args[0][0]
    assert "reviewer_decision" in sql


# ---------------------------------------------------------------------------
# _check_both_agents_approved
# ---------------------------------------------------------------------------


async def test_check_both_agents_approved_returns_true_when_both_approved() -> None:
    from pr_orchestrator.handlers import _check_both_agents_approved

    conn = _mock_conn(fetchone_result=("APPROVED", "APPROVED", 1))
    with patch(
        "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
    ):
        result = await _check_both_agents_approved("org/repo", 1)
    assert result is True


async def test_check_both_agents_approved_returns_false_when_qa_not_approved() -> None:
    from pr_orchestrator.handlers import _check_both_agents_approved

    conn = _mock_conn(fetchone_result=("CHANGES_REQUESTED", "APPROVED", 1))
    with patch(
        "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
    ):
        result = await _check_both_agents_approved("org/repo", 1)
    assert result is False


async def test_check_both_agents_approved_returns_false_when_reviewer_not_approved() -> None:
    from pr_orchestrator.handlers import _check_both_agents_approved

    conn = _mock_conn(fetchone_result=("APPROVED", None, 1))
    with patch(
        "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
    ):
        result = await _check_both_agents_approved("org/repo", 1)
    assert result is False


async def test_check_both_agents_approved_returns_false_when_row_missing() -> None:
    from pr_orchestrator.handlers import _check_both_agents_approved

    conn = _mock_conn(fetchone_result=None)
    with patch(
        "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
    ):
        result = await _check_both_agents_approved("org/repo", 99)
    assert result is False


async def test_check_both_agents_approved_escalates_when_max_cycles_exceeded() -> None:
    from pr_orchestrator.handlers import _check_both_agents_approved

    conn = _mock_conn(fetchone_result=("CHANGES_REQUESTED", "CHANGES_REQUESTED", 5))
    with (
        patch(
            "pr_orchestrator.handlers.psycopg.AsyncConnection.connect", AsyncMock(return_value=conn)
        ),
        patch("pr_orchestrator.handlers._escalate_stuck_pr", new=AsyncMock()) as mock_escalate,
        patch("pr_orchestrator.handlers.settings") as mock_settings,
    ):
        mock_settings.max_review_cycles = 3
        result = await _check_both_agents_approved("org/repo", 1)

    assert result is False
    mock_escalate.assert_called_once_with("org/repo", 1)


# ---------------------------------------------------------------------------
# on_pull_request — only processes relevant actions
# ---------------------------------------------------------------------------


async def test_on_pull_request_opened_upserts_pr_and_publishes() -> None:
    from pr_orchestrator.handlers import on_pull_request

    payload = {
        "action": "opened",
        "pull_request": {"number": 5, "head": {"sha": "abc123"}},
        "repository": {"full_name": "org/repo"},
    }
    with (
        patch("pr_orchestrator.handlers._upsert_pr", new=AsyncMock()) as mock_upsert,
        patch("pr_orchestrator.handlers._publish_event", new=AsyncMock()) as mock_publish,
    ):
        await on_pull_request(payload)

    mock_upsert.assert_called_once_with("org/repo", 5, "abc123")
    mock_publish.assert_called_once()


async def test_on_pull_request_closed_action_is_ignored() -> None:
    from pr_orchestrator.handlers import on_pull_request

    payload = {
        "action": "closed",
        "pull_request": {"number": 5, "head": {"sha": "abc"}},
        "repository": {"full_name": "org/repo"},
    }
    with (
        patch("pr_orchestrator.handlers._upsert_pr", new=AsyncMock()) as mock_upsert,
        patch("pr_orchestrator.handlers._publish_event", new=AsyncMock()),
    ):
        await on_pull_request(payload)

    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# on_pull_request_review — bot detection and approval gate
# ---------------------------------------------------------------------------


async def test_on_pull_request_review_records_bot_review() -> None:
    from pr_orchestrator.handlers import on_pull_request_review

    payload = {
        "review": {"user": {"login": "agent-qa-bot[bot]"}, "state": "approved"},
        "pull_request": {
            "number": 3,
            "html_url": "https://github.com/org/repo/pull/3",
            "title": "feat",
        },
        "repository": {"full_name": "org/repo"},
    }
    with (
        patch("pr_orchestrator.handlers._record_agent_review", new=AsyncMock()) as mock_record,
        patch(
            "pr_orchestrator.handlers._check_both_agents_approved",
            new=AsyncMock(return_value=False),
        ),
    ):
        await on_pull_request_review(payload)

    mock_record.assert_called_once_with("org/repo", 3, "agent-qa-bot[bot]", "APPROVED")


async def test_on_pull_request_review_human_review_not_recorded() -> None:
    from pr_orchestrator.handlers import on_pull_request_review

    payload = {
        "review": {"user": {"login": "alice"}, "state": "approved"},
        "pull_request": {
            "number": 3,
            "html_url": "https://github.com/org/repo/pull/3",
            "title": "feat",
        },
        "repository": {"full_name": "org/repo"},
    }
    with (
        patch("pr_orchestrator.handlers._record_agent_review", new=AsyncMock()) as mock_record,
        patch(
            "pr_orchestrator.handlers._check_both_agents_approved",
            new=AsyncMock(return_value=False),
        ),
    ):
        await on_pull_request_review(payload)

    mock_record.assert_not_called()


async def test_on_pull_request_review_requests_human_when_both_approved() -> None:
    from pr_orchestrator.handlers import on_pull_request_review

    payload = {
        "review": {"user": {"login": "agent-reviewer-bot[bot]"}, "state": "approved"},
        "pull_request": {
            "number": 3,
            "html_url": "https://github.com/org/repo/pull/3",
            "title": "feat",
        },
        "repository": {"full_name": "org/repo"},
    }
    with (
        patch("pr_orchestrator.handlers._record_agent_review", new=AsyncMock()),
        patch(
            "pr_orchestrator.handlers._check_both_agents_approved", new=AsyncMock(return_value=True)
        ),
        patch("pr_orchestrator.handlers._request_human_review", new=AsyncMock()) as mock_human,
    ):
        await on_pull_request_review(payload)

    mock_human.assert_called_once()
