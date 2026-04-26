import pytest
from orchestrator.routing import MAX_RETRIES, route_arch_approval, route_pr_approval, route_reviewer


@pytest.mark.parametrize(
    "approval_granted,expected",
    [
        (True, "engineer"),
        (False, "architect"),
        (None, "architect"),
    ],
)
def test_route_arch_approval(approval_granted: bool | None, expected: str) -> None:
    assert route_arch_approval({"approval_granted": approval_granted}) == expected


def test_route_reviewer_no_issues() -> None:
    state = {"retry_count": 0, "test_results": {"failed": False, "review_issues": False}}
    assert route_reviewer(state) == "await_pr_approval"


def test_route_reviewer_test_failed() -> None:
    state = {"retry_count": 0, "test_results": {"failed": True}}
    assert route_reviewer(state) == "engineer"


def test_route_reviewer_review_issues() -> None:
    state = {"retry_count": 0, "test_results": {"review_issues": True}}
    assert route_reviewer(state) == "engineer"


def test_route_reviewer_empty_test_results() -> None:
    state = {"retry_count": 0, "test_results": {}}
    assert route_reviewer(state) == "await_pr_approval"


def test_route_reviewer_none_test_results() -> None:
    state = {"retry_count": 0, "test_results": None}
    assert route_reviewer(state) == "await_pr_approval"


def test_route_reviewer_at_max_retries_routes_to_fail() -> None:
    state = {"retry_count": MAX_RETRIES, "test_results": {"failed": True}}
    assert route_reviewer(state) == "fail"


def test_route_reviewer_max_retries_overrides_clean_results() -> None:
    state = {"retry_count": MAX_RETRIES, "test_results": {}}
    assert route_reviewer(state) == "fail"


def test_route_reviewer_below_max_retries_still_routes_to_engineer() -> None:
    state = {"retry_count": MAX_RETRIES - 1, "test_results": {"failed": True}}
    assert route_reviewer(state) == "engineer"


@pytest.mark.parametrize(
    "approval_granted,expected",
    [
        (True, "devops"),
        (False, "__end__"),
        (None, "__end__"),
    ],
)
def test_route_pr_approval(approval_granted: bool | None, expected: str) -> None:
    assert route_pr_approval({"approval_granted": approval_granted}) == expected
