from typing import Any

from ..state import ProjectState


async def await_arch_approval_node(state: ProjectState) -> dict[str, Any]:
    """Interrupt node — LangGraph pauses here for human approval of the architecture."""
    # Graph compiled with interrupt_before=["await_arch_approval"], so execution
    # stops before this node runs. When resumed, approval_granted is already set.
    return {"current_phase": "design", "approval_required": False}


async def await_pr_approval_node(state: ProjectState) -> dict[str, Any]:
    """Interrupt node — LangGraph pauses here for human approval of the PR."""
    return {"current_phase": "review", "approval_required": False}


async def fail_node(state: ProjectState) -> dict[str, Any]:
    return {"current_phase": "failed"}
