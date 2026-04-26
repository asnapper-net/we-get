from unittest.mock import MagicMock, patch

from agents_base.agent import AgentResult, BaseAgent


def _make_agent(**kwargs) -> BaseAgent:
    defaults = dict(
        name="test",
        mcp_servers=[],
        model="claude-sonnet-4-6",
        workflow_run_id="run-1",
    )
    defaults.update(kwargs)
    with patch("agents_base.agent.anthropic.AsyncAnthropic"):
        return BaseAgent(**defaults)


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------


def test_extract_text_single_text_block() -> None:
    block = MagicMock(spec=["text"])
    block.text = "Hello"
    response = MagicMock(content=[block])
    assert BaseAgent._extract_text(response) == "Hello"


def test_extract_text_multiple_blocks_joined() -> None:
    b1, b2 = MagicMock(spec=["text"]), MagicMock(spec=["text"])
    b1.text, b2.text = "Hello", "World"
    response = MagicMock(content=[b1, b2])
    assert BaseAgent._extract_text(response) == "Hello\nWorld"


def test_extract_text_skips_blocks_without_text() -> None:
    non_text_block = MagicMock(spec=[])  # no .text attribute
    text_block = MagicMock(spec=["text"])
    text_block.text = "Hi"
    response = MagicMock(content=[non_text_block, text_block])
    assert BaseAgent._extract_text(response) == "Hi"


def test_extract_text_empty_content() -> None:
    response = MagicMock(content=[])
    assert BaseAgent._extract_text(response) == ""


# ---------------------------------------------------------------------------
# _extract_tool_calls
# ---------------------------------------------------------------------------


def test_extract_tool_calls_returns_tool_use_blocks() -> None:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "search"
    block.input = {"query": "test"}
    response = MagicMock(content=[block])

    calls = BaseAgent._extract_tool_calls(response)

    assert len(calls) == 1
    assert calls[0]["name"] == "search"
    assert calls[0]["input"] == {"query": "test"}
    assert calls[0]["result"] is None


def test_extract_tool_calls_ignores_non_tool_blocks() -> None:
    block = MagicMock()
    block.type = "text"
    response = MagicMock(content=[block])
    assert BaseAgent._extract_tool_calls(response) == []


def test_extract_tool_calls_multiple() -> None:
    b1, b2 = MagicMock(), MagicMock()
    b1.type, b1.name, b1.input = "tool_use", "read_file", {"path": "/a"}
    b2.type, b2.name, b2.input = "tool_use", "write_file", {"path": "/b", "content": "x"}
    response = MagicMock(content=[b1, b2])
    calls = BaseAgent._extract_tool_calls(response)
    assert len(calls) == 2
    assert calls[0]["name"] == "read_file"
    assert calls[1]["name"] == "write_file"


# ---------------------------------------------------------------------------
# _build_mcp_server_configs
# ---------------------------------------------------------------------------


def test_build_mcp_server_configs_known_servers() -> None:
    with patch("agents_base.agent.agent_settings") as mock_settings:
        mock_settings.mcp_github_url = "http://github-mcp:8080"
        mock_settings.mcp_slack_url = "http://slack-mcp:8080"
        agent = _make_agent(mcp_servers=["github", "slack"])
        configs = agent._build_mcp_server_configs()

    assert len(configs) == 2
    by_name = {c["name"]: c["url"] for c in configs}
    assert by_name["github"] == "http://github-mcp:8080"
    assert by_name["slack"] == "http://slack-mcp:8080"
    assert all(c["type"] == "url" for c in configs)


def test_build_mcp_server_configs_unknown_server_is_skipped() -> None:
    with patch("agents_base.agent.agent_settings"):
        agent = _make_agent(mcp_servers=["does_not_exist"])
        configs = agent._build_mcp_server_configs()
    assert configs == []


def test_build_mcp_server_configs_empty_list() -> None:
    with patch("agents_base.agent.agent_settings"):
        agent = _make_agent(mcp_servers=[])
        configs = agent._build_mcp_server_configs()
    assert configs == []


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------


def test_agent_result_defaults() -> None:
    result = AgentResult(text="hello")
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.tool_calls == []


def test_agent_result_with_values() -> None:
    result = AgentResult(text="hi", input_tokens=100, output_tokens=50, tool_calls=[{"name": "x"}])
    assert result.input_tokens == 100
    assert result.tool_calls == [{"name": "x"}]
