"""Read-only MCP tools for a locally configured ApplyWise account."""

import logging
import os
import re
from datetime import datetime
from typing import Literal

from bson import ObjectId
from bson.errors import InvalidId
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pymongo.errors import PyMongoError

from app.db.mongo import analyses, jobs, profiles, users
from app.services.semantic_search import profile_chunks

logger = logging.getLogger("applywise.mcp")
server = MCPServer("ApplyWise")
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=False)

JobStatus = Literal["all", "saved", "applied", "assessment", "interview", "offer", "rejected"]

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "our", "the", "their", "to", "with", "you", "your",
}


def _configured_user_id() -> str:
    email = os.getenv("APPLYWISE_MCP_USER_EMAIL", "").strip().lower()
    if not email:
        raise ValueError("MCP is not configured yet. Set APPLYWISE_MCP_USER_EMAIL in the local .env file.")
    try:
        user = users.find_one({"email": email}, {"_id": 1})
    except PyMongoError as exc:
        logger.exception("ApplyWise MCP could not reach MongoDB")
        raise ValueError(
            "ApplyWise could not reach MongoDB. Start Docker Desktop, then run "
            "'docker compose up -d mongo' from the ApplyWise project folder and try again."
        ) from exc
    if user is None:
        raise ValueError("The configured email was not found in ApplyWise. Check APPLYWISE_MCP_USER_EMAIL in .env.")
    return str(user["_id"])


@server.tool(annotations=READ_ONLY)
def list_my_opportunities(status: JobStatus = "all", limit: int = 20) -> list[dict[str, str]]:
    """List this configured ApplyWise account's saved opportunities. This tool is read-only."""
    try:
        user_id = _configured_user_id()
        safe_limit = max(1, min(limit, 50))
        query: dict[str, str] = {"user_id": user_id}
        if status != "all":
            query["status"] = status
        results = []
        for job in jobs.find(query).sort("created_at", -1).limit(safe_limit):
            created_at = job.get("created_at")
            results.append({
                "id": str(job["_id"]),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "status": job.get("status", "saved"),
                "created_at": created_at.isoformat() if isinstance(created_at, datetime) else "",
                "url": job.get("url", ""),
            })
        return results
    except ValueError as exc:
        return [{"error": str(exc)}]


@server.tool(annotations=READ_ONLY)
def get_my_latest_role_analysis(job_id: str) -> dict[str, object]:
    """Return the latest saved role analysis for one of this account's opportunities. Read-only; does not call Gemini."""
    try:
        user_id = _configured_user_id()
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise ValueError("Use an opportunity id returned by list_my_opportunities.") from exc
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        if jobs.find_one({"_id": object_id, "user_id": user_id}, {"_id": 1}) is None:
            return {"error": "That opportunity was not found in the configured ApplyWise account."}
        saved = analyses.find_one(
            {"job_id": object_id, "user_id": user_id},
            sort=[("created_at", -1)],
            projection={"result": 1},
        )
        if saved is None:
            return {"message": "No saved role analysis exists for this opportunity yet."}
        return saved.get("result", {})
    except PyMongoError as exc:
        logger.exception("ApplyWise MCP could not read the requested analysis")
        return {"error": "ApplyWise could not reach MongoDB. Start Docker Desktop and the ApplyWise MongoDB container, then retry."}


@server.tool(annotations=READ_ONLY)
def search_my_profile_evidence(query: str, limit: int = 5) -> list[dict[str, object]]:
    """Search saved profile text locally using keyword overlap. Read-only; does not send profile text to Gemini."""
    try:
        user_id = _configured_user_id()
        profile = profiles.find_one({"_id": f"profile:{user_id}"}, {"skills": 1, "experience_evidence": 1})
    except ValueError as exc:
        return [{"error": str(exc)}]
    except PyMongoError as exc:
        logger.exception("ApplyWise MCP could not read the configured profile")
        return [{"error": "ApplyWise could not reach MongoDB. Start Docker Desktop and the ApplyWise MongoDB container, then retry."}]
    if profile is None:
        return []

    query_terms = {
        term.casefold()
        for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+#.-]*", query)
        if len(term) > 1 and term.casefold() not in STOP_WORDS
    }
    if not query_terms:
        return []

    ranked = []
    for chunk in profile_chunks(profile.get("skills") or "", profile.get("experience_evidence") or ""):
        chunk_terms = {
            term.casefold()
            for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+#.-]*", chunk["text"])
            if len(term) > 1 and term.casefold() not in STOP_WORDS
        }
        matched_terms = sorted(query_terms & chunk_terms)
        if matched_terms:
            ranked.append({
                "source": chunk["source"],
                "text": chunk["text"][:600],
                "matched_terms": matched_terms,
                "similarity": round(len(matched_terms) / len(query_terms), 3),
            })
    ranked.sort(key=lambda item: (item["similarity"], len(item["matched_terms"])), reverse=True)
    return ranked[:max(1, min(limit, 10))]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server.run(transport="stdio")
