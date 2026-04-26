from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    workflow_id: str
    phase: Literal["architecture", "pr", "deployment-staging", "deployment-production"]
    artifact_url: str
    summary: str
    reasoning: list[str]
    risks: list[str]
    token_cost: int = 0
    concerns_for_human: list[str] = []


class ApprovalDecision(BaseModel):
    workflow_id: str
    decision: Literal["approve", "reject", "request_changes"]
    approver: str
    feedback: str = ""
    decided_at: datetime = datetime.utcnow()
