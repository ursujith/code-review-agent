from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal["bug", "security", "performance", "maintainability", "testing", "other"]


class ReviewFinding(BaseModel):
    file_path: str = Field(min_length=1, max_length=500)
    line_number: int = Field(ge=1)
    severity: Severity
    category: Category
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=10, max_length=3000)
    recommendation: str = Field(min_length=5, max_length=2000)
    evidence: str = Field(min_length=3, max_length=1200)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("file_path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        value = value.replace("\\", "/").strip()
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("Finding path must be repository-relative")
        return value


class ReviewSummary(BaseModel):
    overview: str = Field(max_length=3000)
    risk_level: Literal["critical", "high", "medium", "low", "none"]
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=100)


class ReviewResult(BaseModel):
    provider: str = "openai-compatible"
    model: str
    summary: ReviewSummary
    accepted_findings: list[ReviewFinding]
    rejected_findings: int
    reviewed_files: int
    reviewed_added_lines: int
