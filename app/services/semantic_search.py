import hashlib
import math
import os
import re

from google.genai import types
from pymongo.collection import Collection

from app.services.gemini_client import create_gemini_client


def profile_chunks(skills: str, experience_evidence: str) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(source: str, text: str) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        key = (source, text.casefold())
        if key not in seen:
            seen.add(key)
            chunks.append({"source": source, "text": text})

    for skill in re.split(r"[,;|\n]+", skills):
        add("Skills", skill)

    for line in re.split(r"\r?\n+", experience_evidence):
        line = line.strip()
        if not line:
            continue
        if len(line) <= 800:
            add("Experience", line)
            continue
        words = line.split()
        segment: list[str] = []
        segment_size = 0
        for word in words:
            if segment and segment_size + len(word) + 1 > 800:
                add("Experience", " ".join(segment))
                segment = []
                segment_size = 0
            segment.append(word)
            segment_size += len(word) + 1
        add("Experience", " ".join(segment))

    return chunks[:99]


def _embed_texts(texts: list[str]) -> list[list[float]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")

    client = create_gemini_client(api_key)
    response = client.models.embed_content(
        model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").strip(),
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    embeddings = response.embeddings or []
    if len(embeddings) != len(texts) or any(not item.values for item in embeddings):
        raise ValueError("Gemini returned incomplete embeddings")
    return [list(item.values) for item in embeddings]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def search_profile_evidence(
    query: str,
    skills: str,
    experience_evidence: str,
    user_id: str,
    vector_cache: Collection,
) -> list[dict[str, str | float]]:
    chunks = profile_chunks(skills, experience_evidence)
    if not chunks:
        return []

    content_hash = hashlib.sha256(
        "\n".join(f"{chunk['source']}:{chunk['text']}" for chunk in chunks).encode("utf-8")
    ).hexdigest()
    cache_id = f"{user_id}:{content_hash}"
    cached = vector_cache.find_one({"_id": cache_id}, {"vectors": 1})

    if cached and len(cached.get("vectors", [])) == len(chunks):
        query_vector = _embed_texts([query])[0]
        vectors = cached["vectors"]
    else:
        embedded = _embed_texts([query, *(chunk["text"] for chunk in chunks)])
        query_vector, vectors = embedded[0], embedded[1:]
        vector_cache.replace_one(
            {"_id": cache_id},
            {"_id": cache_id, "user_id": user_id, "content_hash": content_hash, "vectors": vectors},
            upsert=True,
        )

    ranked = [
        {**chunk, "similarity": round(_cosine_similarity(query_vector, vector), 4)}
        for chunk, vector in zip(chunks, vectors)
    ]
    ranked.sort(key=lambda result: result["similarity"], reverse=True)
    return ranked[:5]
