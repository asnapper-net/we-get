from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .nodes import (
    architect_node,
    await_arch_approval_node,
    await_pr_approval_node,
    devops_node,
    engineer_node,
    fail_node,
    pm_node,
    qa_node,
    reviewer_node,
)
from .routing import route_arch_approval, route_pr_approval, route_reviewer
from .state import ProjectState


def build_graph(checkpointer: Any) -> CompiledStateGraph[Any, Any, Any, Any]:
    builder: StateGraph[Any, Any, Any, Any] = StateGraph(ProjectState)

    builder.add_node("pm", pm_node)
    builder.add_node("architect", architect_node)
    builder.add_node("await_arch_approval", await_arch_approval_node)
    builder.add_node("engineer", engineer_node)
    builder.add_node("qa", qa_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("await_pr_approval", await_pr_approval_node)
    builder.add_node("devops", devops_node)
    builder.add_node("fail", fail_node)

    builder.set_entry_point("pm")
    builder.add_edge("pm", "architect")
    builder.add_edge("architect", "await_arch_approval")
    builder.add_conditional_edges(
        "await_arch_approval",
        route_arch_approval,
        {"engineer": "engineer", "architect": "architect"},
    )
    builder.add_edge("engineer", "qa")
    builder.add_edge("qa", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        route_reviewer,
        {"engineer": "engineer", "await_pr_approval": "await_pr_approval", "fail": "fail"},
    )
    builder.add_conditional_edges(
        "await_pr_approval",
        route_pr_approval,
        {"devops": "devops", "__end__": END},
    )
    builder.add_edge("devops", END)
    builder.add_edge("fail", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["await_arch_approval", "await_pr_approval"],
    )
