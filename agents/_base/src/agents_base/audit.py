import json
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog

log = structlog.get_logger()

_UPSERT_DDL = """\
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id BIGSERIAL PRIMARY KEY,
    workflow_id TEXT,
    agent_name TEXT,
    tool TEXT,
    args JSONB,
    result JSONB,
    ts TIMESTAMPTZ DEFAULT NOW()
);
"""


async def ensure_schema(conn_str: str) -> None:
    async with await psycopg.AsyncConnection.connect(conn_str) as conn:
        await conn.execute(_UPSERT_DDL)
        await conn.commit()


async def log_tool_call(
    conn_str: str,
    workflow_id: str,
    agent_name: str,
    tool: str,
    args: dict[str, Any],
    result: Any,
) -> None:
    try:
        async with await psycopg.AsyncConnection.connect(conn_str) as conn:
            await conn.execute(
                "INSERT INTO mcp_audit_log (workflow_id, agent_name, tool, args, result, ts)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    workflow_id,
                    agent_name,
                    tool,
                    json.dumps(args),
                    json.dumps(result),
                    datetime.now(UTC),
                ),
            )
            await conn.commit()
    except Exception:
        log.warning("audit.log_failed", workflow_id=workflow_id, tool=tool)
