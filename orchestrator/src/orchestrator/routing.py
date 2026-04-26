from .state import ProjectState

MAX_RETRIES = 3


def route_arch_approval(state: ProjectState) -> str:
    if state.get("approval_granted"):
        return "engineer"
    return "architect"


def route_reviewer(state: ProjectState) -> str:
    if state.get("retry_count", 0) >= MAX_RETRIES:
        return "fail"
    test_results = state.get("test_results") or {}
    if test_results.get("failed") or test_results.get("review_issues"):
        return "engineer"
    return "await_pr_approval"


def route_pr_approval(state: ProjectState) -> str:
    if state.get("approval_granted"):
        return "devops"
    return "__end__"
