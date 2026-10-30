from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import ProcessingMode


def _csv(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelPools:
    analysis: tuple[str, ...]
    image: tuple[str, ...]
    video_short: tuple[str, ...]
    video_medium: tuple[str, ...]
    video_long: tuple[str, ...]

    def video_for(self, duration_seconds: int) -> tuple[str, ...]:
        if duration_seconds <= 12:
            return self.video_short
        if duration_seconds <= 20:
            return self.video_medium or self.video_short
        return self.video_long or self.video_medium or self.video_short


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    inbound_token: str
    workspace: Path
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_site_url: str
    openrouter_app_name: str
    public_base_url: str
    asset_signing_secret: str
    quality: ModelPools
    cost_effective: ModelPools
    quality_image_resolution: str
    cost_image_resolution: str
    quality_video_resolution: str
    cost_video_resolution: str
    max_upload_bytes: int
    max_output_bytes: int
    max_workers: int
    request_timeout_seconds: int
    video_poll_seconds: float
    retention_hours: int
    output_hosts: tuple[str, ...]
    video_postprocess_required: bool

    @classmethod
    def from_env(cls) -> "Settings":
        quality_video = _csv("FRAMEFORGE_QUALITY_VIDEO_MODELS")
        cost_video = _csv("FRAMEFORGE_COST_VIDEO_MODELS")
        settings = cls(
            host=os.getenv("FRAMEFORGE_HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")),
            inbound_token=os.getenv("FRAMEFORGE_ENGINE_TOKEN", ""),
            workspace=Path(os.getenv("FRAMEFORGE_WORKSPACE", ".runtime")),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", ""),
            openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "My Jersey Frame Forge AI"),
            public_base_url=os.getenv("FRAMEFORGE_PUBLIC_BASE_URL", "").rstrip("/"),
            asset_signing_secret=os.getenv("FRAMEFORGE_ASSET_SIGNING_SECRET", ""),
            quality=ModelPools(
                analysis=_csv("FRAMEFORGE_QUALITY_ANALYSIS_MODELS"),
                image=_csv("FRAMEFORGE_QUALITY_IMAGE_MODELS"),
                video_short=_csv("FRAMEFORGE_QUALITY_VIDEO_SHORT_MODELS") or quality_video,
                video_medium=_csv("FRAMEFORGE_QUALITY_VIDEO_MEDIUM_MODELS") or quality_video,
                video_long=_csv("FRAMEFORGE_QUALITY_VIDEO_LONG_MODELS") or quality_video,
            ),
            cost_effective=ModelPools(
                analysis=_csv("FRAMEFORGE_COST_ANALYSIS_MODELS"),
                image=_csv("FRAMEFORGE_COST_IMAGE_MODELS"),
                video_short=_csv("FRAMEFORGE_COST_VIDEO_SHORT_MODELS") or cost_video,
                video_medium=_csv("FRAMEFORGE_COST_VIDEO_MEDIUM_MODELS") or cost_video,
                video_long=_csv("FRAMEFORGE_COST_VIDEO_LONG_MODELS") or cost_video,
            ),
            quality_image_resolution=os.getenv("FRAMEFORGE_QUALITY_IMAGE_RESOLUTION", "4K"),
            cost_image_resolution=os.getenv("FRAMEFORGE_COST_IMAGE_RESOLUTION", "2K"),
            quality_video_resolution=os.getenv("FRAMEFORGE_QUALITY_VIDEO_RESOLUTION", "1080p"),
            cost_video_resolution=os.getenv("FRAMEFORGE_COST_VIDEO_RESOLUTION", "720p"),
            max_upload_bytes=int(os.getenv("FRAMEFORGE_MAX_UPLOAD_MIB", "50")) * 1024 * 1024,
            max_output_bytes=int(os.getenv("FRAMEFORGE_MAX_OUTPUT_MIB", "600")) * 1024 * 1024,
            max_workers=max(1, int(os.getenv("FRAMEFORGE_MAX_WORKERS", "4"))),
            request_timeout_seconds=max(30, int(os.getenv("FRAMEFORGE_REQUEST_TIMEOUT_SECONDS", "600"))),
            video_poll_seconds=max(1.0, float(os.getenv("FRAMEFORGE_VIDEO_POLL_SECONDS", "5"))),
            retention_hours=max(1, int(os.getenv("FRAMEFORGE_RETENTION_HOURS", "24"))),
            output_hosts=tuple(host.lower() for host in _csv("FRAMEFORGE_OUTPUT_HOSTS")),
            video_postprocess_required=_bool("FRAMEFORGE_VIDEO_POSTPROCESS_REQUIRED", True),
        )
        settings.workspace.mkdir(parents=True, exist_ok=True)
        if settings.host not in {"127.0.0.1", "localhost", "::1"} and not settings.inbound_token:
            raise RuntimeError("FRAMEFORGE_ENGINE_TOKEN is required for a public bind.")
        return settings

    def pools_for(self, mode: ProcessingMode) -> ModelPools:
        return self.quality if mode == ProcessingMode.QUALITY else self.cost_effective

    def configured_for_mockup(self, mode: ProcessingMode) -> bool:
        pools = self.pools_for(mode)
        return bool(self.openrouter_api_key and pools.analysis and pools.image)

    def configured_for_video(self, mode: ProcessingMode, duration_seconds: int) -> bool:
        return bool(
            self.openrouter_api_key
            and self.public_base_url.startswith("https://")
            and self.asset_signing_secret
            and self.pools_for(mode).video_for(duration_seconds)
        )

    def image_resolution_for(self, mode: ProcessingMode) -> str:
        return self.quality_image_resolution if mode == ProcessingMode.QUALITY else self.cost_image_resolution

    def video_resolution_for(self, mode: ProcessingMode) -> str:
        return self.quality_video_resolution if mode == ProcessingMode.QUALITY else self.cost_video_resolution

