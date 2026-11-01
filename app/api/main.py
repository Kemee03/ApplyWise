import hashlib
import io
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from docx import Document
from pypdf import PdfReader

from app.api.schemas import JobAnalysisResult, JobCreate, JobRead, JobStatusUpdate, ProfileRead, ProfileSearchRequest, ProfileUpdate
from app.db.mongo import agent_runs, analyses, application_briefs, client, initialize_database, jobs, profile_vectors, profiles, sessions, users
from app.services.agent_workflow import STEP_NAMES, execute_application_workflow
from app.services.application_brief import create_application_brief
from app.services.gemini_analysis import analyze_job_with_gemini
from app.services.semantic_search import search_profile_evidence

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
SESSION_DAYS = 14
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
password_hash = PasswordHash.recommended()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield
    client.close()


app = FastAPI(
    title="ApplyWise API",
    description="A job search copilot that keeps your applications grounded in your experience.",
    version="0.3.0",
    lifespan=lifespan,
)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(user: dict) -> dict:
    return {"id": str(user["_id"]), "email": user["email"], "full_name": user.get("full_name", "")}


def set_session(response: Response, user_id: str) -> None:
    token = secrets.token_urlsafe(40)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    sessions.insert_one({"token_hash": token_digest(token), "user_id": user_id, "expires_at": expires})
    response.set_cookie(
        "applywise_session", token, httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=SESSION_DAYS * 24 * 60 * 60, path="/",
    )


def current_user(applywise_session: str | None = Cookie(default=None)) -> dict:
    if not applywise_session:
        raise HTTPException(status_code=401, detail="Please sign in to continue")
    session = sessions.find_one({"token_hash": token_digest(applywise_session), "expires_at": {"$gt": datetime.now(timezone.utc)}})
    if session is None:
        raise HTTPException(status_code=401, detail="Your session expired. Please sign in again.")
    user = users.find_one({"_id": session["user_id"]})
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue")
    return user


def job_document(document: dict) -> dict:
    document["id"] = str(document.pop("_id"))
    document.pop("legacy_postgres_id", None)
    document.pop("user_id", None)
    return document


def profile_document(document: dict | None) -> dict | None:
    if document is None:
        return None
    document["id"] = str(document.pop("_id"))
    document.pop("user_id", None)
    return document


@app.get("/", include_in_schema=False)
def website() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(WEB_DIR / "login.html")


@app.get("/signup", include_in_schema=False)
def signup_page() -> FileResponse:
    return FileResponse(WEB_DIR / "signup.html")


@app.get("/app", include_in_schema=False)
def workspace_page() -> FileResponse:
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    initialize_database()
    return {"status": "ok", "app": "ApplyWise", "database": "connected"}


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, response: Response) -> dict:
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    # Claim the single user's pre-account local data for the first account only.
    first_account = users.count_documents({}) == 0
    user_id = str(ObjectId())
    user = {"_id": user_id, "email": email, "full_name": payload.full_name.strip(), "password_hash": password_hash.hash(payload.password), "created_at": datetime.now(timezone.utc)}
    try:
        users.insert_one(user)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc

    if first_account:
        jobs.update_many({"user_id": {"$exists": False}}, {"$set": {"user_id": user_id}})
        old_profile = profiles.find_one({"_id": "candidate"})
        if old_profile:
            old_profile.pop("_id", None)
            old_profile["user_id"] = user_id
            old_profile["_id"] = f"profile:{user_id}"
            profiles.insert_one(old_profile)
            profiles.delete_one({"_id": "candidate"})
        user_jobs = list(jobs.find({"user_id": user_id}, {"_id": 1}))
        for job in user_jobs:
            analyses.update_many({"job_id": job["_id"], "user_id": {"$exists": False}}, {"$set": {"user_id": user_id}})
    set_session(response, user_id)
    return {"user": public_user(user)}


@app.post("/auth/login")
def login(payload: Credentials, response: Response) -> dict:
    email = payload.email.strip().lower()
    user = users.find_one({"email": email})
    if user is None or not password_hash.verify(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    set_session(response, str(user["_id"]))
    return {"user": public_user(user)}


@app.post("/auth/logout")
def logout(response: Response, applywise_session: str | None = Cookie(default=None)) -> dict[str, str]:
    if applywise_session:
        sessions.delete_one({"token_hash": token_digest(applywise_session)})
    response.delete_cookie("applywise_session", path="/", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return {"status": "signed_out"}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"user": public_user(user)}


@app.get("/jobs", response_model=list[JobRead])
def list_jobs(user: dict = Depends(current_user)) -> list[dict]:
    return [job_document(job) for job in jobs.find({"user_id": str(user["_id"])}).sort("created_at", -1)]


@app.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, user: dict = Depends(current_user)) -> dict:
    document = payload.model_dump()
    document.update({"status": "saved", "created_at": datetime.now(timezone.utc), "user_id": str(user["_id"])})
    result = jobs.insert_one(document)
    document["id"] = str(result.inserted_id)
    document.pop("user_id", None)
    return document


@app.patch("/jobs/{job_id}", response_model=JobRead)
def update_job_status(job_id: str, payload: JobStatusUpdate, user: dict = Depends(current_user)) -> dict:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    result = jobs.update_one(
        {"_id": object_id, "user_id": str(user["_id"])},
        {"$set": {"status": payload.status, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_document(jobs.find_one({"_id": object_id, "user_id": str(user["_id"])}))


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: dict = Depends(current_user)) -> dict[str, str]:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    owner = str(user["_id"])
    result = jobs.delete_one({"_id": object_id, "user_id": owner})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    analyses.delete_many({"job_id": object_id, "user_id": owner})
    application_briefs.delete_many({"job_id": object_id, "user_id": owner})
    agent_runs.delete_many({"job_id": job_id, "user_id": owner})
    return {"status": "deleted"}


@app.get("/profile", response_model=ProfileRead | None)
def get_profile(user: dict = Depends(current_user)) -> dict | None:
    return profile_document(profiles.find_one({"_id": f"profile:{user['_id']}"}))


@app.put("/profile", response_model=ProfileRead)
def save_profile(payload: ProfileUpdate, user: dict = Depends(current_user)) -> dict:
    now = datetime.now(timezone.utc)
    profile_id = f"profile:{user['_id']}"
    profiles.update_one(
        {"_id": profile_id},
        {"$set": {**payload.model_dump(), "updated_at": now}, "$setOnInsert": {"_id": profile_id, "user_id": str(user["_id"])}},
        upsert=True,
    )
    profile_vectors.delete_many({"user_id": str(user["_id"])})
    return profile_document(profiles.find_one({"_id": profile_id}))


@app.post("/profile/search")
def search_saved_profile(payload: ProfileSearchRequest, user: dict = Depends(current_user)) -> dict:
    owner = str(user["_id"])
    profile = profiles.find_one({"_id": f"profile:{owner}"})
    if profile is None:
        raise HTTPException(status_code=409, detail="Save your profile before searching its evidence")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise HTTPException(status_code=503, detail="Gemini is not configured. Add GEMINI_API_KEY to .env and restart ApplyWise.")
    try:
        matches = search_profile_evidence(
            payload.query,
            profile.get("skills") or "",
            profile.get("experience_evidence") or "",
            owner,
            profile_vectors,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Gemini could not search your profile. Check the key, model access, and free-tier quota, then try again.") from exc
    return {"query": payload.query, "matches": matches}


@app.post("/profile/resume")
async def extract_resume_text(resume: UploadFile = File(...), user: dict = Depends(current_user)) -> dict[str, str]:
    filename = (resume.filename or "").lower()
    if not filename.endswith((".pdf", ".docx")):
        raise HTTPException(status_code=415, detail="Choose a PDF or DOCX resume.")
    content = await resume.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Resume files must be 5 MB or smaller.")
    try:
        if filename.endswith(".pdf"):
            pages = PdfReader(io.BytesIO(content)).pages
            extracted = "\n".join(page.extract_text() or "" for page in pages)
        else:
            document = Document(io.BytesIO(content))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            parts.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells if cell.text.strip())
            extracted = "\n".join(parts)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="We couldn’t read this file. Try exporting the resume as a regular PDF or DOCX.") from exc
    extracted = extracted.strip()[:50000]
    if not extracted:
        raise HTTPException(status_code=422, detail="No selectable text was found. Scanned/image-only PDFs need OCR; try a text-based PDF or DOCX.")
    return {"filename": resume.filename or "resume", "text": extracted}


@app.post("/jobs/{job_id}/analyze", response_model=JobAnalysisResult)
def analyze_saved_job(job_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    owner = str(user["_id"])
    job = jobs.find_one({"_id": object_id, "user_id": owner})
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = profiles.find_one({"_id": f"profile:{owner}"})
    if profile is None:
        raise HTTPException(status_code=409, detail="Save your profile before analyzing a job")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise HTTPException(status_code=503, detail="Gemini is not configured. Add GEMINI_API_KEY to .env and restart ApplyWise.")
    try:
        result = analyze_job_with_gemini(job["description"], profile.get("skills", ""), profile.get("experience_evidence", ""))
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Gemini could not complete the analysis. Check the key, model access, and free-tier quota, then try again.") from exc
    result["job_id"] = job_id
    analyses.insert_one({"job_id": object_id, "user_id": owner, "result": result, "created_at": datetime.now(timezone.utc)})
    return result


@app.post("/jobs/{job_id}/agent-run", status_code=status.HTTP_202_ACCEPTED)
def start_agent_run(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
) -> dict:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    owner = str(user["_id"])
    job = jobs.find_one({"_id": object_id, "user_id": owner})
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = profiles.find_one({"_id": f"profile:{owner}"})
    if profile is None:
        raise HTTPException(status_code=409, detail="Save your profile before running the ApplyWise agent")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise HTTPException(status_code=503, detail="Gemini is not configured. Add GEMINI_API_KEY to .env and restart ApplyWise.")

    context_hash = hashlib.sha256("\0".join([
        "langgraph-v3-quality-audit-fix",
        job.get("title", ""),
        job.get("company", ""),
        job.get("description", ""),
        profile.get("skills") or "",
        profile.get("experience_evidence") or "",
    ]).encode("utf-8")).hexdigest()
    cached_run = agent_runs.find_one(
        {"user_id": owner, "job_id": job_id, "context_hash": context_hash, "status": "completed"},
        sort=[("created_at", -1)],
    )
    if cached_run:
        return {"id": cached_run["_id"], "status": "completed", "cached": True}
    active_run = agent_runs.find_one(
        {"user_id": owner, "job_id": job_id, "context_hash": context_hash, "status": "running"},
        sort=[("created_at", -1)],
    )
    if active_run:
        return {"id": active_run["_id"], "status": "running", "cached": True}

    failed_run = agent_runs.find_one(
        {"user_id": owner, "job_id": job_id, "context_hash": context_hash, "status": "failed"},
        sort=[("created_at", -1)],
    )
    if failed_run:
        run_id = failed_run["_id"]
        now = datetime.now(timezone.utc)
        agent_runs.update_one(
            {"_id": run_id, "user_id": owner, "status": "failed"},
            {"$set": {"status": "running", "updated_at": now}, "$unset": {"error": ""}},
        )
        background_tasks.add_task(execute_application_workflow, run_id, job_id, owner)
        return {"id": run_id, "status": "running", "resumed": True}

    run_id = str(ObjectId())
    now = datetime.now(timezone.utc)
    agent_runs.insert_one({
        "_id": run_id,
        "user_id": owner,
        "job_id": job_id,
        "context_hash": context_hash,
        "status": "running",
        "current_step": 0,
        "steps": [{"name": name, "status": "pending", "detail": ""} for name in STEP_NAMES],
        "created_at": now,
        "updated_at": now,
    })
    background_tasks.add_task(execute_application_workflow, run_id, job_id, owner)
    return {"id": run_id, "status": "running"}


@app.get("/agent-runs/{run_id}")
def get_agent_run(run_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        ObjectId(run_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Agent run not found") from exc
    run = agent_runs.find_one({"_id": run_id, "user_id": str(user["_id"])})
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    run["id"] = str(run.pop("_id"))
    run.pop("user_id", None)
    return run


@app.get("/jobs/{job_id}/agent-runs/latest")
def get_latest_agent_run(job_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    owner = str(user["_id"])
    if jobs.find_one({"_id": object_id, "user_id": owner}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    run = agent_runs.find_one({"job_id": job_id, "user_id": owner}, sort=[("created_at", -1)])
    if run is None:
        return {"run": None}
    run["id"] = str(run.pop("_id"))
    run.pop("user_id", None)
    return {"run": run}


@app.get("/jobs/{job_id}/application-brief")
def get_application_brief(job_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    owner = str(user["_id"])
    if jobs.find_one({"_id": object_id, "user_id": owner}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    saved = application_briefs.find_one(
        {"job_id": object_id, "user_id": owner},
        sort=[("created_at", -1)],
    )
    return {"job_id": job_id, "brief": saved["brief"] if saved else None}


@app.post("/jobs/{job_id}/application-brief")
def draft_application_brief(job_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    owner = str(user["_id"])
    job = jobs.find_one({"_id": object_id, "user_id": owner})
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = profiles.find_one({"_id": f"profile:{owner}"})
    if profile is None:
        raise HTTPException(status_code=409, detail="Save your profile before preparing an application")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise HTTPException(status_code=503, detail="Gemini is not configured. Add GEMINI_API_KEY to .env and restart ApplyWise.")
    try:
        try:
            relevant_evidence = search_profile_evidence(
                f"{job.get('title', '')}\n{job.get('description', '')}",
                profile.get("skills") or "",
                profile.get("experience_evidence") or "",
                owner,
                profile_vectors,
            )
        except Exception:
            logger.exception("Semantic retrieval failed for application brief; using complete profile evidence")
            relevant_evidence = []
        brief = create_application_brief(
            job.get("title", ""),
            job.get("company", ""),
            job.get("description", ""),
            profile.get("skills") or "",
            profile.get("experience_evidence") or "",
            relevant_evidence,
        )
    except Exception as exc:
        logger.exception("Gemini application brief generation failed")
        raise HTTPException(status_code=502, detail="Gemini couldn’t finish a valid application draft. Please try again shortly.") from exc
    application_briefs.insert_one({
        "job_id": object_id,
        "user_id": owner,
        "brief": brief,
        "created_at": datetime.now(timezone.utc),
    })
    return {"job_id": job_id, **brief}
