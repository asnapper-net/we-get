import hashlib
import hmac
import time
from unittest.mock import patch

import pytest
from approval_service.config import settings
from approval_service.server import _changes_modal, _channel_for_phase, _verify_slack_signature
from fastapi import HTTPException

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
