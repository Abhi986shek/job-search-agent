"""Pydantic request/response models and the normalised job shape shared by all sources."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SourceName = Literal["predictleads", "serpapi", "adzuna", "freehire"]
ALL_SOURCES: tuple[str, ...] = ("predictleads", "serpapi", "adzuna", "freehire")

JobStatus = Literal["new", "shortlisted", "applied", "rejected", "archived"]
RoleStatus = Literal["proposed", "confirmed", "rejected"]


# â”€â”€ Normalised job (every source maps into this) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class NormalizedJob(BaseModel):
    source: str
    source_job_id: str
    title: str
    company: str = ""
    company_domain: str = ""
    location: str = ""
    description: str = ""
    posted_at: datetime | None = None
    posted_text: str = ""
    apply_url: str = ""
    source_url: str = ""
    salary_text: str = ""
    employment_type: str = ""
    via: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class UsageEvent(BaseModel):
    source: str
    endpoint: str
    status_code: int | None = None
    credits_used: float = 0
    note: str = ""


class SourceResult(BaseModel):
    source: str
    status: Literal["ok", "not_configured", "error", "skipped"]
    message: str = ""
    jobs: list[NormalizedJob] = Field(default_factory=list)
    fetched: int = 0
    usage: list[UsageEvent] = Field(default_factory=list)


# â”€â”€ Target roles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TargetRoleIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    seniority: str = Field(default="", max_length=50)
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = False
    onet_codes: list[str] = Field(default_factory=list)
    status: RoleStatus = "confirmed"

    @field_validator("onet_codes")
    @classmethod
    def check_onet(cls, v: list[str]) -> list[str]:
        import re
        out = []
        for code in v:
            code = code.strip()
            if not re.fullmatch(r"\d{2}-\d{4}\.\d{2}", code):
                raise ValueError(f"Invalid O*NET code '{code}'. Expected format 15-1252.00")
            out.append(code)
        return out


class TargetRoleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    seniority: str | None = None
    locations: list[str] | None = None
    remote_ok: bool | None = None
    onet_codes: list[str] | None = None
    status: RoleStatus | None = None

    @field_validator("onet_codes")
    @classmethod
    def check_onet(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else TargetRoleIn.check_onet(v)


# â”€â”€ Search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SearchRequest(BaseModel):
    target_role_id: int | None = None
    query: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=100, description="City for SerpApi and Adzuna, e.g. Bengaluru")
    country: str = Field(default="India", max_length=60, description="Country or state for PredictLeads")
    onet_codes: list[str] = Field(default_factory=list)
    sources: list[SourceName] = Field(default_factory=lambda: list(ALL_SOURCES))
    max_days_old: int = Field(default=30, ge=1, le=365)
    limit_per_source: int = Field(default=25, ge=1, le=100)
    keyword_filter_predictleads: bool = Field(
        default=True,
        description="PredictLeads filters by O*NET code, not title. Keep only results whose title shares a word with the query.",
    )


class CompanyJobsRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=200)
    limit: int = Field(default=100, ge=1, le=1000)


# â”€â”€ Jobs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class JobUpdate(BaseModel):
    status: JobStatus


# â”€â”€ Guidance URLs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class GuidanceUrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str = Field(default="", max_length=300)
    company: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    pasted_description: str = Field(default="", max_length=20000)
    note: str = Field(default="", max_length=2000)


class GuidanceUrlBatch(BaseModel):
    items: list[GuidanceUrlIn] = Field(min_length=1, max_length=200)


# â”€â”€ Assistant â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
