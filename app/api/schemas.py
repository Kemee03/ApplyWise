from datetime import datetime

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    url: str = Field(default="", max_length=2000)


class JobStatusUpdate(BaseModel):
    status: Literal["saved", "applied", "assessment", "interview", "offer", "rejected"]


class JobRead(BaseModel):
    id: str
    title: str
    company: str
    description: str
    status: str
    created_at: datetime
    url: str = ""


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(default="", max_length=200)
    target_role: str = Field(default="", max_length=200)
    skills: str = Field(default="")
    experience_evidence: str = Field(default="")


class ProfileRead(ProfileUpdate):
    id: str
    updated_at: datetime


class ProfileSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=3, max_length=500)


class SkillFinding(BaseModel):
    skill: str
    match: str
    evidence: list[str]


class JobAnalysisResult(BaseModel):
    job_id: str
    score: int | None
    recognized_requirements: int
    matched: int
    partial: int
    gaps: int
    skills: list[SkillFinding]
    summary: str
    note: str
    quality_checks: dict[str, Any] | None = None
