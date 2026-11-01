import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "applywise")
client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
database = client[MONGODB_DATABASE]
jobs = database["jobs"]
profiles = database["profiles"]
analyses = database["job_analyses"]
profile_vectors = database["profile_vectors"]
application_briefs = database["application_briefs"]
agent_runs = database["agent_runs"]
users = database["users"]
sessions = database["sessions"]


def initialize_database() -> None:
    database.command("ping")
    jobs.create_index([("created_at", -1)])
    analyses.create_index([("job_id", 1), ("created_at", -1)])
    application_briefs.create_index([("user_id", 1), ("job_id", 1), ("created_at", -1)])
    agent_runs.create_index([("user_id", 1), ("created_at", -1)])
    users.create_index("email", unique=True)
    sessions.create_index("token_hash", unique=True)
    sessions.create_index("expires_at", expireAfterSeconds=0)
