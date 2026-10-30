from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessingMode(str, Enum):
    QUALITY = "quality"
    COST_EFFECTIVE = "cost_effective"


class AspectRatio(str, Enum):
    PORTRAIT = "9:16"
    LANDSCAPE = "16:9"
    SQUARE = "1:1"
    SOCIAL = "4:5"


class BrandDetails(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    brand_name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=180)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    website: str | None = Field(default=None, max_length=180)
    address: str | None = Field(default=None, max_length=240)
    social_handle: str | None = Field(default=None, max_length=120)

    def lines(self) -> list[str]:
        clean = lambda value: " ".join(value.split()) if value else ""
        header = " · ".join(clean(value) for value in (self.brand_name, self.tagline) if value)
        contact = " · ".join(clean(value) for value in (self.phone, self.email, self.website, self.social_handle) if value)
        return [line for line in (header, contact, clean(self.address)) if line]


class MockupOptions(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    template_id: str = Field(min_length=2, max_length=80)
    mode: ProcessingMode = ProcessingMode.QUALITY
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT
    style_notes: str | None = Field(default=None, max_length=1000)
    brand: BrandDetails = Field(default_factory=BrandDetails)


class VideoOptions(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    template_id: str = Field(min_length=2, max_length=80)
    mode: ProcessingMode = ProcessingMode.QUALITY
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT
    duration_seconds: int = Field(default=10, ge=10, le=30)
    style_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("duration_seconds")
    @classmethod
    def whole_seconds(cls, value: int) -> int:
        return int(value)


class JobKind(str, Enum):
    MOCKUP = "mockup"
    VIDEO = "video"


class JobState(BaseModel):
    job_id: str
    kind: JobKind
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    mode: ProcessingMode
    template_id: str
    aspect_ratio: AspectRatio
    duration_seconds: int | None = None
    source_job_id: str | None = None
    selected_model: str | None = None
    analysis: dict[str, Any] | None = None
    prompt: str | None = None
    brand: BrandDetails = Field(default_factory=BrandDetails)
    has_logo: bool = False
    output_name: str | None = None
    output_content_type: str | None = None
    error: dict[str, str] | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    def public(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"prompt"})
        payload["output_ready"] = self.status == "ready" and bool(self.output_name)
        if payload["output_ready"]:
            payload["download_url"] = f"/api/frameforge/jobs/{self.job_id}/output"
        return payload

