import logging
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any, TypedDict

from bson import ObjectId
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.graph import END, START, StateGraph

from app.db.mongo import (
    MONGODB_DATABASE,
    agent_runs,
    analyses,
    application_briefs,
    client as mongo_client,
    jobs,
    profile_vectors,
    profiles,
)
from app.services.application_brief import create_application_brief
from app.services.gemini_analysis import analyze_job_with_gemini
from app.services.semantic_search import search_profile_evidence

logger = logging.getLogger(__name__)

STEP_NAMES = [
    "Review the role requirements",
    "Find relevant evidence in your profile",
    "Draft your application brief",
]


class ApplicationWorkflowState(TypedDict, total=False):
    run_id: str
    job_id: str
    user_id: str
    job: dict[str, str]
    profile: dict[str, str]
    analysis: dict[str, Any]
    evidence: list[dict[str, Any]]
    brief: dict[str, Any]


def _user_facing_workflow_error(exc: Exception) -> str:
    """Translate common Gemini outages into useful, safe UI messages."""
    code = getattr(exc, "code", None)
    error_text = str(exc)
    if code == 429 or "RESOURCE_EXHAUSTED" in error_text:
        retry = re.search(r"Please retry in ([\d.]+h[\d.]+m[\d.]+s)", error_text, re.IGNORECASE)
        if retry:
            retry_delay = re.sub(r"(\d+)\.\d+(?=s$)", r"\1", retry.group(1))
            return (
                "Gemini's free-tier daily request quota is exhausted. Gemini says to try again in "
                f"about {retry_delay}. Wait for the quota reset before starting another run; retrying now "
                "will not bypass the limit. ApplyWise did not submit an application."
            )
        return (
            "Gemini's free-tier request quota is exhausted. Wait for the quota reset before starting "
            "another run; retrying now will not bypass the limit. ApplyWise did not submit an application."
        )
    if code == 503 or "UNAVAILABLE" in error_text:
        return "Gemini is temporarily unavailable. Wait a little before trying again. ApplyWise did not submit an application."
    return "The ApplyWise workflow could not finish. Review the step status, then try again. No application was submitted."


def _update_step(run_filter: dict[str, str], active_steps: set[int], active_lock: Lock, index: int, state: str, detail: str = "") -> None:
    with active_lock:
        if state == "running":
            active_steps.add(index)
        else:
            active_steps.discard(index)
    now = datetime.now(timezone.utc)
    agent_runs.update_one(
        run_filter,
        {"$set": {
            f"steps.{index}.status": state,
            f"steps.{index}.detail": detail,
            "current_step": index if state == "running" else index + 1,
            "updated_at": now,
        }},
    )


def _build_workflow(run_filter: dict[str, str], active_steps: set[int], active_lock: Lock):
    def load_context(state: ApplicationWorkflowState) -> dict[str, Any]:
        job = jobs.find_one({"_id": ObjectId(state["job_id"]), "user_id": state["user_id"]})
        profile = profiles.find_one({"_id": f"profile:{state['user_id']}"})
        if job is None or profile is None:
            raise ValueError("The saved role or profile is no longer available. Refresh the workspace and try again.")
        return {
            "job": {
                "id": state["job_id"],
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "description": job.get("description", ""),
            },
            "profile": {
                "skills": profile.get("skills") or "",
                "experience_evidence": profile.get("experience_evidence") or "",
            },
        }

    def analyze_role(state: ApplicationWorkflowState) -> dict[str, Any]:
        _update_step(run_filter, active_steps, active_lock, 0, "running", "Comparing the saved role requirements with your profile.")
        job, profile = state["job"], state["profile"]
        result = analyze_job_with_gemini(job["description"], profile["skills"], profile["experience_evidence"])
        result["job_id"] = job["id"]
        analyses.insert_one({
            "job_id": ObjectId(job["id"]),
            "user_id": state["user_id"],
            "result": result,
            "created_at": datetime.now(timezone.utc),
        })
        agent_runs.update_one(run_filter, {"$set": {"result.analysis": result}})
        _update_step(run_filter, active_steps, active_lock, 0, "completed", "Role analysis is ready.")
        return {"analysis": result}

    def find_profile_evidence(state: ApplicationWorkflowState) -> dict[str, Any]:
        _update_step(run_filter, active_steps, active_lock, 1, "running", "Searching your saved skills and experience by meaning.")
        job, profile = state["job"], state["profile"]
        try:
            evidence = search_profile_evidence(
                f"{job['title']}\n{job['description']}",
                profile["skills"],
                profile["experience_evidence"],
                state["user_id"],
                profile_vectors,
            )
            detail = f"Found {len(evidence)} relevant profile snippets."
        except Exception:
            logger.exception("Agent semantic retrieval failed; continuing with complete profile evidence")
            evidence = []
            detail = "Semantic search was unavailable; the draft will use your saved profile evidence."
        _update_step(run_filter, active_steps, active_lock, 1, "completed", detail)
        return {"evidence": evidence}

    def draft_application_brief(state: ApplicationWorkflowState) -> dict[str, Any]:
        _update_step(run_filter, active_steps, active_lock, 2, "running", "Writing a draft grounded in your saved evidence.")
        job, profile = state["job"], state["profile"]
        brief = create_application_brief(
            job["title"],
            job["company"],
            job["description"],
            profile["skills"],
            profile["experience_evidence"],
            state.get("evidence", []),
        )
        now = datetime.now(timezone.utc)
        application_briefs.insert_one({
            "job_id": ObjectId(job["id"]),
            "user_id": state["user_id"],
            "brief": brief,
            "created_at": now,
        })
        agent_runs.update_one(run_filter, {"$set": {"result.brief": brief, "updated_at": now}})
        _update_step(run_filter, active_steps, active_lock, 2, "completed", "Draft saved to this opportunity for your review.")
        return {"brief": brief}

    def finish(state: ApplicationWorkflowState) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        agent_runs.update_one(
            run_filter,
            {"$set": {
                "status": "completed",
                "current_step": len(STEP_NAMES),
                "result": {"analysis": state["analysis"], "brief": state["brief"]},
                "updated_at": now,
                "completed_at": now,
            }},
        )
        return {}

    builder = StateGraph(ApplicationWorkflowState)
    builder.add_node("load_context", load_context)
    builder.add_node("analyze_role", analyze_role)
    builder.add_node("find_profile_evidence", find_profile_evidence)
    builder.add_node("draft_application_brief", draft_application_brief)
    builder.add_node("finish", finish)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "analyze_role")
    builder.add_edge("load_context", "find_profile_evidence")
    builder.add_edge(["analyze_role", "find_profile_evidence"], "draft_application_brief")
    builder.add_edge("draft_application_brief", "finish")
    builder.add_edge("finish", END)

    checkpointer = MongoDBSaver(
        mongo_client,
        db_name=MONGODB_DATABASE,
        checkpoint_collection_name="applywise_agent_checkpoints",
        writes_collection_name="applywise_agent_checkpoint_writes",
    )
    return builder.compile(checkpointer=checkpointer)


def execute_application_workflow(run_id: str, job_id: str, user_id: str) -> None:
    """Run the agent as a checkpointed LangGraph workflow with parallel independent steps."""
    run_filter = {"_id": run_id, "user_id": user_id}
    active_steps: set[int] = set()
    active_lock = Lock()
    try:
        workflow = _build_workflow(run_filter, active_steps, active_lock)
        workflow.invoke(
            {"run_id": run_id, "job_id": job_id, "user_id": user_id},
            config={"configurable": {"thread_id": run_id}},
        )
    except Exception as exc:
        logger.exception("ApplyWise LangGraph workflow failed")
        failure_update = {
            "status": "failed",
            "error": _user_facing_workflow_error(exc),
            "updated_at": datetime.now(timezone.utc),
        }
        with active_lock:
            failed_steps = list(active_steps)
        for active_step in failed_steps:
            failure_update[f"steps.{active_step}.status"] = "failed"
            failure_update[f"steps.{active_step}.detail"] = "This step did not finish."
        agent_runs.update_one(run_filter, {"$set": failure_update})
