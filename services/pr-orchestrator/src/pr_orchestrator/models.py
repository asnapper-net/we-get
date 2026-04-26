from datetime import datetime

from pydantic import BaseModel


class PRState(BaseModel):
    repo: str
    pr_number: int
    head_sha: str
    review_cycle_count: int = 0
    qa_decision: str | None = None
    reviewer_decision: str | None = None
    human_requested_at: datetime | None = None
    human_decision: str | None = None
