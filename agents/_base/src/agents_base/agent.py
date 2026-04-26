from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .audit import log_tool_call
from .config import agent_settings

log = structlog.get_logger()

_MCP_SERVER_MAP = {
    "github": lambda: agent_settings.mcp_github_url,
    "jira": lambda: agent_settings.mcp_jira_url,
    "confluence": lambda: agent_settings.mcp_confluence_url,
    "kubernetes": lambda: agent_settings.mcp_kubernetes_url,
    "slack": lambda: agent_settings.mcp_slack_url,
    "playwright": lambda: agent_settings.mcp_playwright_url,
    "filesystem": lambda: agent_settings.mcp_filesystem_url,
    "qdrant": lambda: agent_settings.mcp_qdrant_url,
}


@dataclass
class AgentResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class BaseAgent:
    def __init__(
        self,
        name: str,
        mcp_servers: list[str],
        model: str,
        workflow_run_id: str,
        max_tokens: int = 8192,
    ) -> None:
        self.name = name
        self.model = model
        self.workflow_run_id = workflow_run_id
        self.max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=agent_settings.anthropic_api_key)
        self._mcp_servers = mcp_servers
        self._langfuse_trace_id: str | None = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.RateLimitError)),
        reraise=True,
    )
    async def run(self, system: str, user: str) -> AgentResult:
        log.info("agent.run", agent=self.name, workflow=self.workflow_run_id, model=self.model)
        start = time.monotonic()

        mcp_servers = self._build_mcp_server_configs()

        response = await self._client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            betas=["mcp-client-2025-04-04"],
            mcp_servers=mcp_servers,  # type: ignore[arg-type]
        )

        tool_calls = self._extract_tool_calls(response)
        for tc in tool_calls:
            await log_tool_call(
                conn_str=agent_settings.database_url,
                workflow_id=self.workflow_run_id,
                agent_name=self.name,
                tool=tc.get("name", ""),
                args=tc.get("input", {}),
                result=tc.get("result"),
            )

        text = self._extract_text(response)
        elapsed = time.monotonic() - start
        log.info(
            "agent.done",
            agent=self.name,
            workflow=self.workflow_run_id,
            elapsed=round(elapsed, 2),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return AgentResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            tool_calls=tool_calls,
        )

    def _build_mcp_server_configs(self) -> list[dict[str, Any]]:
        configs = []
        for name in self._mcp_servers:
            if name not in _MCP_SERVER_MAP:
                log.warning("agent.unknown_mcp_server", server=name)
                continue
            configs.append({"type": "url", "url": _MCP_SERVER_MAP[name](), "name": name})
        return configs

    @staticmethod
    def _extract_text(response: Any) -> str:
        parts = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "tool_use":
                calls.append({"name": block.name, "input": block.input, "result": None})
        return calls
