import re

SKILL_CATALOG: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "SQL": ("sql",),
    "PostgreSQL": ("postgresql", "postgres"),
    "FastAPI": ("fastapi",),
    "LLMs": ("llm", "llms", "large language model", "large language models"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "Docker": ("docker", "docker compose", "docker-compose"),
    "LangGraph": ("langgraph",),
    "Agent orchestration": ("agent orchestration", "agentic workflow", "tool calling"),
    "Embeddings": ("embedding", "embeddings"),
    "pgvector": ("pgvector",),
    "REST API": ("rest api", "rest apis", "restful api", "restful apis"),
    "Machine learning": ("machine learning", "ml model", "ml models"),
}



def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def analyze_job(job_description: str, profile_skills: str, experience_evidence: str) -> dict:
    skill_lines = [line.strip() for line in re.split(r"[,\n;]+", profile_skills) if line.strip()]
    evidence_lines = [line.strip() for line in experience_evidence.splitlines() if line.strip()]
    findings = []

    for skill, aliases in SKILL_CATALOG.items():
        if not contains_any(job_description, aliases):
            continue

        listed = contains_any("\n".join(skill_lines), aliases)
        supporting_lines = [line for line in evidence_lines if contains_any(line, aliases)]
        if supporting_lines:
            match = "matched"
            evidence = [line[:240] for line in supporting_lines[:3]]
        elif listed:
            match = "partial"
            evidence = ["Listed in your skills; add a project or work example to strengthen the evidence."]
        else:
            match = "gap"
            evidence = []

        findings.append({"skill": skill, "match": match, "evidence": evidence})

    matched = sum(item["match"] == "matched" for item in findings)
    partial = sum(item["match"] == "partial" for item in findings)
    gaps = sum(item["match"] == "gap" for item in findings)
    recognized = len(findings)
    score = round((matched + 0.5 * partial) / recognized * 100) if recognized else None

    if recognized:
        summary = f"Found {recognized} known skill keywords in the job description."
    else:
        summary = "No skills from the current keyword catalog were found. Add common skills or wait for the richer job parser."

    return {
        "score": score,
        "recognized_requirements": recognized,
        "matched": matched,
        "partial": partial,
        "gaps": gaps,
        "skills": findings,
        "summary": summary,
        "note": "Baseline keyword analysis: it does not yet understand context or distinguish required skills from preferred ones. Treat the score as a guide, not a hiring prediction.",
    }
