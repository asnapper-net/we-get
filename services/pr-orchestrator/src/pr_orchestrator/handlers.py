"""GitHub webhook event handlers."""

from __future__ import annotations

import json
from typing import Any

import aio_pika
import httpx
import psycopg
import structlog
from slack_sdk.web.async_client import AsyncWebClient

from .config import settings

log = structlog.get_logger()

_DDL = """\
CREATE TABLE IF NOT EXISTS pr_state (
    repo TEXT NOT NULL,
    pr_number INT NOT NULL,
    head_sha TEXT NOT NULL,
    review_cycle_count INT DEFAULT 0,
    qa_decision TEXT,
    reviewer_decision TEXT,
    human_requested_at TIMESTAMPTZ,
    human_decision TEXT,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (repo, pr_number)
);
"""


async def ensure_schema() -> None:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(_DDL)
        await conn.commit()


async def on_pull_request(payload: dict[str, Any]) -> None:
    action = payload.get("action")
    pr = payload.get("pull_request", {})
    repo = payload["repository"]["full_name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]

    if action in ("opened", "synchronize", "reopened"):
        await _upsert_pr(repo, pr_number, head_sha)
        await _publish_event(
            "pr.opened", {"repo": repo, "pr_number": pr_number, "head_sha": head_sha}
        )
        log.info("pr.opened", repo=repo, pr_number=pr_number)


async def on_pull_request_review(payload: dict[str, Any]) -> None:
    review = payload.get("review", {})
    pr = payload.get("pull_request", {})
    repo = payload["repository"]["full_name"]
    pr_number = pr["number"]
    reviewer_login = review.get("user", {}).get("login", "")
    state = review.get("state", "").upper()

    if reviewer_login.endswith("[bot]"):
        await _record_agent_review(repo, pr_number, reviewer_login, state)

    both_approved = await _check_both_agents_approved(repo, pr_number)
    if both_approved:
        await _request_human_review(repo, pr_number, pr)


async def _upsert_pr(repo: str, pr_number: int, head_sha: str) -> None:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(
            "INSERT INTO pr_state (repo, pr_number, head_sha) VALUES (%s, %s, %s)"
            " ON CONFLICT (repo, pr_number) DO UPDATE"
            " SET head_sha=EXCLUDED.head_sha, qa_decision=NULL, reviewer_decision=NULL,"
            "     human_requested_at=NULL, last_updated=NOW(),"
            "     review_cycle_count=pr_state.review_cycle_count + 1",
            (repo, pr_number, head_sha),
        )
        await conn.commit()


async def _record_agent_review(repo: str, pr_number: int, bot_login: str, state: str) -> None:
    col = "qa_decision" if "qa" in bot_login else "reviewer_decision"
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(
            f"UPDATE pr_state SET {col}=%s, last_updated=NOW() WHERE repo=%s AND pr_number=%s",
            (state, repo, pr_number),
        )
        await conn.commit()


async def _check_both_agents_approved(repo: str, pr_number: int) -> bool:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        row = await (
            await conn.execute(
                "SELECT qa_decision, reviewer_decision, review_cycle_count"
                " FROM pr_state WHERE repo=%s AND pr_number=%s",
                (repo, pr_number),
            )
        ).fetchone()
    if not row:
        return False
    qa_ok = (row[0] or "").upper() == "APPROVED"
    rev_ok = (row[1] or "").upper() == "APPROVED"
    cycle_count: int = row[2] or 0

    if cycle_count >= settings.max_review_cycles and not (qa_ok and rev_ok):
        await _escalate_stuck_pr(repo, pr_number)
        return False

    return qa_ok and rev_ok


async def _request_human_review(repo: str, pr_number: int, pr: dict[str, Any]) -> None:
    log.info("pr.human_review_requested", repo=repo, pr_number=pr_number)
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(
            "UPDATE pr_state SET human_requested_at=NOW() WHERE repo=%s AND pr_number=%s",
            (repo, pr_number),
        )
        await conn.commit()

    client = AsyncWebClient(token=settings.slack_bot_token)
    await client.chat_postMessage(
        channel=settings.slack_review_channel,
        text=(
            f":white_check_mark: Both agents approved <{pr['html_url']}|{repo}#{pr_number}>."
            f" *{pr['title']}* — please review."
        ),
    )


async def _escalate_stuck_pr(repo: str, pr_number: int) -> None:
    log.warning("pr.stuck", repo=repo, pr_number=pr_number)
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels",
            json={"labels": ["needs-human-help"]},
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )


async def _publish_event(routing_key: str, body: dict[str, Any]) -> None:
    try:
        connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                "agent.events", aio_pika.ExchangeType.TOPIC, durable=True
            )
            await exchange.publish(
                aio_pika.Message(body=json.dumps(body).encode()),
                routing_key=routing_key,
            )
    except Exception:
        log.warning("pr.publish_failed", routing_key=routing_key)
