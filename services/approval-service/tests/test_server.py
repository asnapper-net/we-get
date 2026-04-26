import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from approval_service.config import settings
from approval_service.server import _changes_modal, _channel_for_phase, _verify_slack_signature, app
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# _verify_slack_signature
# ---------------------------------------------------------------------------


def _sign(body: bytes, timestamp: str, secret: str = "test-secret") -> str:
    base = f"v0:{timestamp}:{body.decode()}"
    return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def test_verify_slack_signature_valid() -> None:
    body = b"payload=test"
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    with patch.object(settings, "slack_signing_secret", "test-secret"):
        _verify_slack_signature(body, sig, ts)  # must not raise


def test_verify_slack_signature_expired_timestamp_raises_400() -> None:
    body = b"payload=test"
    ts = str(int(time.time()) - 400)  # 400 s > 300 s threshold
    sig = _sign(body, ts)
    with (
        patch.object(settings, "slack_signing_secret", "test-secret"),
        pytest.raises(HTTPException) as exc,
    ):
        _verify_slack_signature(body, sig, ts)
    assert exc.value.status_code == 400


def test_verify_slack_signature_wrong_secret_raises_401() -> None:
    body = b"payload=test"
    ts = str(int(time.time()))
    sig = _sign(body, ts, secret="wrong-secret")
    with (
        patch.object(settings, "slack_signing_secret", "real-secret"),
        pytest.raises(HTTPException) as exc,
    ):
        _verify_slack_signature(body, sig, ts)
    assert exc.value.status_code == 401


def test_verify_slack_signature_tampered_body_raises_401() -> None:
    body = b"payload=original"
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    with (
        patch.object(settings, "slack_signing_secret", "test-secret"),
        pytest.raises(HTTPException) as exc,
    ):
        _verify_slack_signature(b"payload=tampered", sig, ts)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("ts", ["", "not-a-number"])
def test_verify_slack_signature_invalid_timestamp_raises_400(ts: str) -> None:
    body = b"payload=test"
    sig = _sign(body, ts)
    with (
        patch.object(settings, "slack_signing_secret", "test-secret"),
        pytest.raises(HTTPException) as exc,
    ):
        _verify_slack_signature(body, sig, ts)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# _channel_for_phase
# ---------------------------------------------------------------------------


def test_channel_for_phase_architecture() -> None:
    assert _channel_for_phase("architecture") == settings.channel_arch


def test_channel_for_phase_pr() -> None:
    assert _channel_for_phase("pr") == settings.channel_prs


def test_channel_for_phase_deployment_staging() -> None:
    assert _channel_for_phase("deployment-staging") == settings.channel_prs


def test_channel_for_phase_deployment_production() -> None:
    assert _channel_for_phase("deployment-production") == settings.channel_prod


def test_channel_for_phase_unknown_falls_back_to_prs() -> None:
    assert _channel_for_phase("something-unexpected") == settings.channel_prs


# ---------------------------------------------------------------------------
# _changes_modal
# ---------------------------------------------------------------------------


def test_changes_modal_type_is_modal() -> None:
    modal = _changes_modal("wf-123")
    assert modal["type"] == "modal"


def test_changes_modal_embeds_workflow_id_in_metadata() -> None:
    modal = _changes_modal("wf-abc")
    assert modal["private_metadata"] == "wf-abc"


def test_changes_modal_has_feedback_input_block() -> None:
    modal = _changes_modal("wf-1")
    assert len(modal["blocks"]) == 1
    block = modal["blocks"][0]
    assert block["type"] == "input"
    assert block["element"]["type"] == "plain_text_input"
    assert block["element"]["multiline"] is True


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


def _mock_conn() -> MagicMock:
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


async def test_healthz() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_approval_request_returns_201() -> None:
    payload = {
        "workflow_id": "wf-1",
        "phase": "pr",
        "artifact_url": "https://github.com/org/repo/pull/1",
        "summary": "Add feature X",
        "reasoning": ["Reason A"],
        "risks": [],
    }
    mock_conn = _mock_conn()
    with (
        patch("approval_service.server.post_approval_request", AsyncMock(return_value="111.222")),
        patch("psycopg.AsyncConnection.connect", AsyncMock(return_value=mock_conn)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/approval-requests", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["workflow_id"] == "wf-1"
    assert data["slack_ts"] == "111.222"


async def test_create_approval_request_invalid_phase_returns_422() -> None:
    payload = {
        "workflow_id": "wf-2",
        "phase": "unknown-phase",
        "artifact_url": "https://example.com",
        "summary": "x",
        "reasoning": [],
        "risks": [],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/approval-requests", json=payload)
    assert resp.status_code == 422


async def test_slack_interactions_approve() -> None:
    ts = str(int(time.time()))
    body = json.dumps({
        "actions": [{"action_id": "approve", "value": "wf-1"}],
        "user": {"id": "U123"},
    }).encode()
    sig = _sign(body, ts)
    with (
        patch.object(settings, "slack_signing_secret", "test-secret"),
        patch("approval_service.server._finalize", AsyncMock()) as mock_fin,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/slack/interactions",
                content=body,
                headers={
                    "x-slack-signature": sig,
                    "x-slack-request-timestamp": ts,
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 200
    mock_fin.assert_awaited_once_with("wf-1", "approve", "U123", "")


async def test_slack_interactions_reject() -> None:
    ts = str(int(time.time()))
    body = json.dumps({
        "actions": [{"action_id": "reject", "value": "wf-2"}],
        "user": {"id": "U456"},
    }).encode()
    sig = _sign(body, ts)
    with (
        patch.object(settings, "slack_signing_secret", "test-secret"),
        patch("approval_service.server._finalize", AsyncMock()) as mock_fin,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/slack/interactions",
                content=body,
                headers={
                    "x-slack-signature": sig,
                    "x-slack-request-timestamp": ts,
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 200
    mock_fin.assert_awaited_once_with("wf-2", "reject", "U456", "")


async def test_slack_interactions_request_changes_returns_modal() -> None:
    ts = str(int(time.time()))
    body = json.dumps({
        "actions": [{"action_id": "request_changes", "value": "wf-3"}],
        "user": {"id": "U789"},
    }).encode()
    sig = _sign(body, ts)
    with patch.object(settings, "slack_signing_secret", "test-secret"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/slack/interactions",
                content=body,
                headers={
                    "x-slack-signature": sig,
                    "x-slack-request-timestamp": ts,
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response_action"] == "push"
    assert data["view"]["private_metadata"] == "wf-3"


async def test_slack_interactions_bad_signature_returns_401() -> None:
    ts = str(int(time.time()))
    body = b'{"actions": []}'
    with patch.object(settings, "slack_signing_secret", "test-secret"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/slack/interactions",
                content=body,
                headers={
                    "x-slack-signature": "v0=badsig",
                    "x-slack-request-timestamp": ts,
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 401


async def test_modal_submit_calls_finalize() -> None:
    body = json.dumps({
        "view": {
            "private_metadata": "wf-10",
            "state": {"values": {"feedback": {"feedback_input": {"value": "Needs more tests"}}}},
        },
        "user": {"id": "U999"},
    }).encode()
    with patch("approval_service.server._finalize", AsyncMock()) as mock_fin:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/slack/modal-submit",
                content=body,
                headers={"content-type": "application/json"},
            )
    assert resp.status_code == 200
    mock_fin.assert_awaited_once_with("wf-10", "request_changes", "U999", "Needs more tests")
