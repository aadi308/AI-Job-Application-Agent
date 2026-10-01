from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.networking import networking_node
from app.agents.resume_writer import resume_writer_node
from app.agents.state import JobApplicationState


def supervisor_router(state: JobApplicationState) -> str:
    """Decide which worker still needs to run, or whether the job is ready for human review."""
    if not state.get("tailored_resume"):
        return "resume_writer"
    if not state.get("outreach_message"):
        return "networking"
    if state.get("human_approved") is None:
        return "human_review"
    return "end"


def supervisor_node(state: JobApplicationState) -> dict:
    # Pure routing hub — the conditional edge below does the actual dispatch, this node
    # exists so routing is a first-class, visible step in the graph rather than baked into
    # the worker nodes themselves.
    return {}


def human_review_node(state: JobApplicationState) -> dict:
    decision = interrupt(
        {
            "message": "Review the tailored resume and outreach draft before finalizing.",
            "job_id": state["job_id"],
            "company": state["company"],
            "title": state["title"],
            "ats_score": state["ats_score"],
            "tailored_resume": state["tailored_resume"],
            "outreach_message": state["outreach_message"],
            "resume_pdf_path": state.get("resume_pdf_path"),
            "resume_valid": state.get("resume_valid"),
            "resume_claim_violations": state.get("resume_claim_violations") or [],
            "resume_pdf_violations": state.get("resume_pdf_violations") or [],
        }
    )
    return {
        "human_approved": bool(decision.get("approved", False)),
        "human_feedback": decision.get("feedback"),
    }


def build_graph():
    graph = StateGraph(JobApplicationState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("resume_writer", resume_writer_node)
    graph.add_node("networking", networking_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "resume_writer": "resume_writer",
            "networking": "networking",
            "human_review": "human_review",
            "end": END,
        },
    )
    graph.add_edge("resume_writer", "supervisor")
    graph.add_edge("networking", "supervisor")
    graph.add_edge("human_review", "supervisor")

    return graph.compile(checkpointer=MemorySaver())
