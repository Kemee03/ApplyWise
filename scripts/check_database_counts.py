"""Show record counts only; do not print job descriptions or profile text."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.postgres_models import CandidateProfile, Job, JobAnalysis  # noqa: E402
from app.db.mongo import analyses, client, jobs, profiles  # noqa: E402

with SessionLocal() as postgres:
    print("PostgreSQL jobs:", postgres.scalar(select(func.count()).select_from(Job)))
    print("PostgreSQL profiles:", postgres.scalar(select(func.count()).select_from(CandidateProfile)))
    print("PostgreSQL analyses:", postgres.scalar(select(func.count()).select_from(JobAnalysis)))

print("MongoDB jobs:", jobs.count_documents({}))
print("MongoDB profiles:", profiles.count_documents({}))
print("MongoDB analyses:", analyses.count_documents({}))
client.close()
