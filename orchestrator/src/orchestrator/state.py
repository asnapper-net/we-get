from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class ProjectState(TypedDict):
    # Identifiers
    jira_ticket_id: str
    github_repo: str
    workflow_run_id: str

    # Artifacts
    requirements_doc: str | None
    architecture_decision: str | None
    pr_url: str | None
    test_results: dict[str, Any] | None
    deployment_status: str | None

    # Control flow
    current_phase: Literal[
        "intake", "design", "implementation", "review", "deploy", "done", "failed"
    ]
    approval_required: bool
    approval_granted: bool | None

    # Conversation + control
    messages: Annotated[list[Any], add_messages]
    errors: list[Any]
    retry_count: int
