import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pr_orchestrator.config import settings
from pr_orchestrator.server import _verify_signature, app

# ---------------------------------------------------------------------------
# _verify_signature
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_valid() -> None:
    body = b'{"action":"opened"}'
    sig = _sign(body, "s3cr3t")
    with patch.object(settings, "github_webhook_secret", "s3cr3t"):
        _verify_signature(body, sig)  # must not raise


def test_verify_signature_invalid_raises_401() -> None:
    body = b'{"action":"opened"}'
    with (
        patch.object(settings, "github_webhook_secret", "s3cr3t"),
        pytest.raises(HTTPException) as exc,
    ):
        _verify_signature(body, "sha256=badhash")
    assert exc.value.status_code == 401


def test_verify_signature_empty_secret_skips_check() -> None:
    body = b'{"action":"opened"}'
    with patch.object(settings, "github_webhook_secret", ""):
        _verify_signature(body, "sha256=anything")  # must not raise


def test_verify_signature_tampered_body_raises_401() -> None:
    body_original = b'{"action":"opened"}'
    sig = _sign(body_original, "s3cr3t")
    with (
        patch.object(settings, "github_webhook_secret", "s3cr3t"),
        pytest.raises(HTTPException) as exc,
    ):
        _verify_signature(b'{"action":"tampered"}', sig)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


async def test_healthz() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 200


async def test_webhook_ignores_unknown_event() -> None:
    body = json.dumps({"action": "opened"}).encode()
    sig = _sign(body, "s3cr3t")
    with patch.object(settings, "github_webhook_secret", "s3cr3t"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/github/webhook",
                content=body,
                headers={
                    "x-hub-signature-256": sig,
                    "x-github-event": "push",
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_webhook_routes_pull_request_event() -> None:
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "head": {"sha": "abc"}},
        "repository": {"full_name": "org/repo"},
    }
    body = json.dumps(payload).encode()
    sig = _sign(body, "s3cr3t")

    mock_handler = AsyncMock(return_value=None)
    with (
        patch.object(settings, "github_webhook_secret", "s3cr3t"),
        patch.dict("pr_orchestrator.server._EVENT_HANDLERS", {"pull_request": mock_handler}),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/github/webhook",
                content=body,
                headers={
                    "x-hub-signature-256": sig,
                    "x-github-event": "pull_request",
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 200
    mock_handler.assert_called_once()


async def test_webhook_rejects_bad_signature() -> None:
    body = json.dumps({"action": "opened"}).encode()
    with patch.object(settings, "github_webhook_secret", "s3cr3t"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/github/webhook",
                content=body,
                headers={
                    "x-hub-signature-256": "sha256=badsig",
                    "x-github-event": "pull_request",
                    "content-type": "application/json",
                },
            )
    assert resp.status_code == 401
