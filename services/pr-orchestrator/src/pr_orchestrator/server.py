import hashlib
import hmac
import json
from typing import Annotated

import structlog
from fastapi import FastAPI, Header, HTTPException, Request

from .config import settings
from .handlers import ensure_schema, on_pull_request, on_pull_request_review

log = structlog.get_logger()
app = FastAPI(title="pr-orchestrator")

_EVENT_HANDLERS = {
    "pull_request": on_pull_request,
    "pull_request_review": on_pull_request_review,
}


@app.on_event("startup")
async def startup() -> None:
    await ensure_schema()


@app.post("/github/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: Annotated[str, Header()] = "",
    x_github_event: Annotated[str, Header()] = "",
) -> dict[str, bool]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    payload = json.loads(body)
    handler = _EVENT_HANDLERS.get(x_github_event)
    if handler:
        await handler(payload)
        log.info("webhook.handled", github_event=x_github_event)
    else:
        log.debug("webhook.ignored", github_event=x_github_event)

    return {"ok": True}


@app.get("/pr-status/{repo:path}/{number}")
async def pr_status(repo: str, number: int) -> dict[str, object]:
    import psycopg

    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM pr_state WHERE repo=%s AND pr_number=%s",
                (repo, number),
            )
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="PR not found")
    cols = [
        "repo",
        "pr_number",
        "head_sha",
        "review_cycle_count",
        "qa_decision",
        "reviewer_decision",
        "human_requested_at",
        "human_decision",
        "last_updated",
    ]
    return dict(zip(cols, row, strict=True))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


def _verify_signature(body: bytes, signature: str) -> None:
    if not settings.github_webhook_secret:
        return
    expected = (
        "sha256="
        + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
