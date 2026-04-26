import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel

from .config import settings
from .graph import build_graph
from .state import ProjectState

log = structlog.get_logger()

_graph: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _graph
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        _graph = build_graph(saver)
        log.info("orchestrator.ready")
        yield
    _graph = None


app = FastAPI(title="agent-platform orchestrator", lifespan=lifespan)


class StartWorkflowRequest(BaseModel):
    jira_ticket_id: str
    github_repo: str


class ResumeWorkflowRequest(BaseModel):
    approval_granted: bool
    feedback: str = ""


@app.post("/workflows", status_code=201)
async def start_workflow(req: StartWorkflowRequest) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    initial_state: ProjectState = {
        "jira_ticket_id": req.jira_ticket_id,
        "github_repo": req.github_repo,
        "workflow_run_id": run_id,
        "requirements_doc": None,
        "architecture_decision": None,
        "pr_url": None,
        "test_results": None,
        "deployment_status": None,
        "current_phase": "intake",
        "approval_required": False,
        "approval_granted": None,
        "messages": [],
        "errors": [],
        "retry_count": 0,
    }
    config = {"configurable": {"thread_id": run_id}}
    await _graph.ainvoke(initial_state, config)
    log.info("workflow.started", run_id=run_id)
    return {"workflow_run_id": run_id}


@app.post("/workflows/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, req: ResumeWorkflowRequest) -> dict[str, Any]:
    config = {"configurable": {"thread_id": workflow_id}}
    update: dict[str, Any] = {
        "approval_granted": req.approval_granted,
        "approval_required": False,
    }
    if req.feedback:
        update["errors"] = [req.feedback]
    await _graph.aupdate_state(config, update)
    await _graph.ainvoke(None, config)
    log.info("workflow.resumed", workflow_id=workflow_id, granted=req.approval_granted)
    return {"workflow_id": workflow_id, "resumed": True}


@app.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": workflow_id}}
    snapshot = await _graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return {"workflow_id": workflow_id, "state": snapshot.values}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    if _graph is None:
        raise HTTPException(status_code=503, detail="graph not initialized")
    return {"status": "ok"}
