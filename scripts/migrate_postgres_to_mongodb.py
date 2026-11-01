"""Copy ApplyWise jobs, profile, and analyses from local PostgreSQL into MongoDB.

This is safe to rerun: imported documents are identified by their legacy PostgreSQL IDs.
It copies data and never deletes or changes anything in PostgreSQL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.db.database import SessionLocal  # noqa: E402
from app.db.postgres_models import CandidateProfile, Job, JobAnalysis  # noqa: E402
from app.db.mongo import MONGODB_DATABASE, MONGODB_URI  # noqa: E402


def main() -> None:
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    mongo_client.admin.command("ping")
    mongo_db = mongo_client[MONGODB_DATABASE]
    mongo_jobs = mongo_db["jobs"]
    mongo_profiles = mongo_db["profiles"]
    mongo_analyses = mongo_db["job_analyses"]

    with SessionLocal() as postgres:
        old_jobs = postgres.scalars(select(Job).order_by(Job.id)).all()
        old_profile = postgres.get(CandidateProfile, 1)
        old_analyses = postgres.scalars(select(JobAnalysis).order_by(JobAnalysis.id)).all()

        migrated_jobs = 0
        id_map: dict[int, ObjectId] = {}
        for job in old_jobs:
            mongo_jobs.update_one(
                {"legacy_postgres_id": job.id},
                {"$setOnInsert": {
                    "_id": ObjectId(),
                    "legacy_postgres_id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "description": job.description,
                    "status": job.status,
                    "created_at": job.created_at or datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            saved = mongo_jobs.find_one({"legacy_postgres_id": job.id}, {"_id": 1})
            id_map[job.id] = saved["_id"]
            migrated_jobs += 1

        migrated_profile = 0
        if old_profile is not None:
            mongo_profiles.update_one(
                {"_id": "candidate"},
                {"$setOnInsert": {
                    "full_name": old_profile.full_name,
                    "target_role": old_profile.target_role,
                    "skills": old_profile.skills,
                    "experience_evidence": old_profile.experience_evidence,
                    "updated_at": old_profile.updated_at or datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            migrated_profile = 1

        migrated_analyses = 0
        for analysis in old_analyses:
            mongo_job_id = id_map.get(analysis.job_id)
            if mongo_job_id is None:
                continue
            result = dict(analysis.result)
            result["job_id"] = str(mongo_job_id)
            mongo_analyses.update_one(
                {"legacy_postgres_id": analysis.id},
                {"$setOnInsert": {
                    "legacy_postgres_id": analysis.id,
                    "job_id": mongo_job_id,
                    "result": result,
                    "created_at": analysis.created_at or datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            migrated_analyses += 1

    mongo_client.close()
    print("Migration copy finished. PostgreSQL was left unchanged.")
    print(f"Jobs copied or already present: {migrated_jobs}")
    print(f"Profile copied or already present: {migrated_profile}")
    print(f"Analyses copied or already present: {migrated_analyses}")


if __name__ == "__main__":
    main()



