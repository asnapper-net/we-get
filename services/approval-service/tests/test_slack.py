from approval_service.models import ApprovalRequest
from approval_service.slack import _build_blocks


def _req(**overrides) -> ApprovalRequest:
    defaults = dict(
        workflow_id="wf-1",
        phase="architecture",
        artifact_url="https://confluence.example.com/adr/1",
        summary="New caching layer design",
        reasoning=["Reduces latency", "Improves resilience"],
        risks=["Cache invalidation complexity"],
        token_cost=1500,
        concerns_for_human=[],
    )
    defaults.update(overrides)
    return ApprovalRequest(**defaults)


def test_blocks_starts_with_header() -> None:
    blocks = _build_blocks(_req())
    assert blocks[0]["type"] == "header"


def test_header_contains_phase_in_uppercase() -> None:
    blocks = _build_blocks(_req(phase="architecture"))
    header_text = blocks[0]["text"]["text"]
    assert "ARCHITECTURE" in header_text


def test_blocks_ends_with_actions() -> None:
    blocks = _build_blocks(_req())
    assert blocks[-1]["type"] == "actions"


def test_action_buttons_are_approve_reject_request_changes() -> None:
    blocks = _build_blocks(_req())
    actions = blocks[-1]
    ids = {e["action_id"] for e in actions["elements"]}
    assert ids == {"approve", "reject", "request_changes"}


def test_action_buttons_carry_workflow_id() -> None:
    blocks = _build_blocks(_req(workflow_id="wf-xyz"))
    actions = blocks[-1]
    values = {e["value"] for e in actions["elements"] if "value" in e}
    assert "wf-xyz" in values


def test_reasoning_bullets_appear_in_blocks() -> None:
    blocks = _build_blocks(_req(reasoning=["Fast", "Cheap"]))
    all_text = " ".join(str(b) for b in blocks)
    assert "• Fast" in all_text
    assert "• Cheap" in all_text


def test_risks_bullets_appear_in_blocks() -> None:
    blocks = _build_blocks(_req(risks=["Data loss", "Downtime"]))
    all_text = " ".join(str(b) for b in blocks)
    assert "• Data loss" in all_text


def test_empty_risks_shows_none_identified() -> None:
    blocks = _build_blocks(_req(risks=[]))
    all_text = " ".join(str(b) for b in blocks)
    assert "None identified" in all_text


def test_concerns_section_present_when_non_empty() -> None:
    blocks = _build_blocks(_req(concerns_for_human=["Security issue detected"]))
    all_text = " ".join(str(b) for b in blocks)
    assert "Security issue detected" in all_text
    assert ":warning:" in all_text


def test_concerns_section_absent_when_empty() -> None:
    blocks = _build_blocks(_req(concerns_for_human=[]))
    all_text = " ".join(str(b) for b in blocks)
    assert ":warning:" not in all_text


def test_token_cost_formatted_with_commas() -> None:
    blocks = _build_blocks(_req(token_cost=2_500_000))
    all_text = " ".join(str(b) for b in blocks)
    assert "2,500,000" in all_text


def test_artifact_url_in_blocks() -> None:
    blocks = _build_blocks(_req(artifact_url="https://example.com/artifact"))
    all_text = " ".join(str(b) for b in blocks)
    assert "https://example.com/artifact" in all_text
