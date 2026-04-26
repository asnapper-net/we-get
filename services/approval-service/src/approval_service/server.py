import hashlib
import hmac
import json
import time
from typing import Annotated, Any

import httpx
import psycopg
import structlog
from fastapi import FastAPI, Header, HTTPException, Request

from .config import settings
from .models import ApprovalRequest
from .slack import post_approval_request, update_message

log = structlog.get_logger()
app = FastAPI(title="approval-service")

_DDL = """\
CREATE TABLE IF NOT EXISTS approval_requests (
    workflow_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    slack_channel TEXT NOT NULL,
    slack_message_ts TEXT NOT NULL,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    decision TEXT,
    approver TEXT,
    feedback TEXT
);
"""


@app.on_event("startup")
async def startup() -> None:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(_DDL)
        await conn.commit()


@app.post("/approval-requests", status_code=201)
async def create_approval_request(req: ApprovalRequest) -> dict[str, Any]:
    ts = await post_approval_request(req)
    channel = _channel_for_phase(req.phase)
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(
            "INSERT INTO approval_requests (workflow_id, phase, slack_channel, slack_message_ts)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (workflow_id) DO UPDATE"
            " SET phase=EXCLUDED.phase, slack_message_ts=EXCLUDED.slack_message_ts",
            (req.workflow_id, req.phase, channel, ts),
        )
        await conn.commit()
    return {"workflow_id": req.workflow_id, "slack_ts": ts}


@app.post("/slack/interactions")
async def slack_interactions(
    request: Request,
    x_slack_signature: Annotated[str, Header()] = "",
    x_slack_request_timestamp: Annotated[str, Header()] = "",
) -> dict[str, Any]:
    body = await request.body()
    _verify_slack_signature(body, x_slack_signature, x_slack_request_timestamp)

    payload = json.loads(request.query_params.get("payload") or body)
    action = payload["actions"][0]
    action_id = action["action_id"]
    workflow_id = action["value"]
    user = payload["user"]["id"]

    if action_id == "request_changes":
        return {"response_action": "push", "view": _changes_modal(workflow_id)}

    approved = action_id == "approve"
    await _finalize(workflow_id, "approve" if approved else "reject", user, "")
    return {"text": f"Decision recorded: {action_id} by <@{user}>"}


@app.post("/slack/modal-submit")
async def modal_submit(request: Request) -> dict[str, Any]:
    body = await request.body()
    payload = json.loads(body)
    workflow_id = payload["view"]["private_metadata"]
    feedback = payload["view"]["state"]["values"]["feedback"]["feedback_input"]["value"]
    user = payload["user"]["id"]
    await _finalize(workflow_id, "request_changes", user, feedback)
    return {}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok"}


async def _finalize(workflow_id: str, decision: str, approver: str, feedback: str) -> None:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        row = await (
            await conn.execute(
                "UPDATE approval_requests"
                " SET decided_at=NOW(), decision=%s, approver=%s, feedback=%s"
                " WHERE workflow_id=%s RETURNING slack_channel, slack_message_ts",
                (decision, approver, feedback, workflow_id),
            )
        ).fetchone()
        await conn.commit()

    if row:
        await update_message(row[0], row[1], f"✅ Decision: *{decision}* by <@{approver}>")

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{settings.orchestrator_url}/workflows/{workflow_id}/resume",
            json={"approval_granted": decision == "approve", "feedback": feedback},
            timeout=30,
        )


def _verify_slack_signature(body: bytes, signature: str, timestamp: str) -> None:
    try:
        ts = float(timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid timestamp") from None
    if abs(time.time() - ts) > 300:
        raise HTTPException(status_code=400, detail="timestamp too old")
    base = f"v0:{timestamp}:{body.decode()}"
    expected = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid signature")


def _channel_for_phase(phase: str) -> str:
    return {
        "architecture": settings.channel_arch,
        "pr": settings.channel_prs,
        "deployment-staging": settings.channel_prs,
        "deployment-production": settings.channel_prod,
    }.get(phase, settings.channel_prs)


def _changes_modal(workflow_id: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Request Changes"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "private_metadata": workflow_id,
        "blocks": [
            {
                "type": "input",
                "block_id": "feedback",
                "label": {"type": "plain_text", "text": "Feedback for the agent"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "feedback_input",
                    "multiline": True,
                },
            }
        ],
    }
