from typing import Any

import structlog
from slack_sdk.web.async_client import AsyncWebClient

from .config import settings
from .models import ApprovalRequest

log = structlog.get_logger()

_CHANNEL_MAP = {
    "architecture": settings.channel_arch,
    "pr": settings.channel_prs,
    "deployment-staging": settings.channel_prs,
    "deployment-production": settings.channel_prod,
}


async def post_approval_request(req: ApprovalRequest) -> str:
    """Post an interactive approval message to Slack. Returns the message timestamp."""
    client = AsyncWebClient(token=settings.slack_bot_token)
    channel = _CHANNEL_MAP.get(req.phase, settings.channel_prs)

    blocks = _build_blocks(req)
    resp = await client.chat_postMessage(channel=channel, blocks=blocks, text=req.summary)
    ts: str = resp["ts"]
    log.info("slack.approval_posted", workflow_id=req.workflow_id, channel=channel, ts=ts)
    return ts


async def update_message(channel: str, ts: str, text: str) -> None:
    client = AsyncWebClient(token=settings.slack_bot_token)
    await client.chat_update(channel=channel, ts=ts, text=text, blocks=[])


def _build_blocks(req: ApprovalRequest) -> list[dict[str, Any]]:
    reasoning_text = "\n".join(f"• {r}" for r in req.reasoning)
    risks_text = "\n".join(f"• {r}" for r in req.risks) if req.risks else "None identified"
    concerns_text = (
        "\n".join(f"• {c}" for c in req.concerns_for_human) if req.concerns_for_human else ""
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{req.phase.upper()}] Approval Required"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": req.summary}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Artifact:*\n<{req.artifact_url}|View>"},
                {"type": "mrkdwn", "text": f"*Token cost:*\n{req.token_cost:,}"},
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Reasoning:*\n{reasoning_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Risks:*\n{risks_text}"}},
    ]

    if concerns_text:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Concerns for human review:*\n{concerns_text}",
                },
            }
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "approve",
                    "value": req.workflow_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "reject",
                    "value": req.workflow_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Request Changes"},
                    "action_id": "request_changes",
                    "value": req.workflow_id,
                },
            ],
        }
    )

    return blocks
