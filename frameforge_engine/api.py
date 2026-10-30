from __future__ import annotations

import hmac
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from . import __version__
from .config import Settings
from .errors import FrameForgeError
from .models import MockupOptions, ProcessingMode, VideoOptions
from .service import SOURCE_TYPES, FrameForgeService, UploadPayload
from .templates import ALL_TEMPLATES, catalog


async def _upload(file: UploadFile, maximum: int) -> UploadPayload:
    content = await file.read(maximum + 1)
    await file.close()
    if not content:
        raise FrameForgeError("EMPTY_UPLOAD", "Uploaded file is empty.", 422)
    if len(content) > maximum:
        raise FrameForgeError("UPLOAD_TOO_LARGE", "Uploaded file exceeds the configured limit.", 413)
    filename = Path(file.filename or "upload.bin").name
    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return UploadPayload(filename, content, content_type)


def create_app(settings: Settings, service: FrameForgeService | None = None) -> FastAPI:
    engine = service or FrameForgeService(settings)

    @asynccontextmanager
    async def lifespan(_app):
        engine.start()
        yield
        engine.close()

    app = FastAPI(
        title="My Jersey Frame Forge AI Engine",
        version=__version__,
        description="Template-driven mockup and optional video generation through OpenRouter.",
        docs_url="/api/frameforge/docs",
        redoc_url=None,
        openapi_url="/api/frameforge/openapi.json",
        lifespan=lifespan,
    )
    app.state.frameforge_service = engine

    @app.exception_handler(FrameForgeError)
    async def frameforge_error(_request, exc: FrameForgeError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    async def access(authorization: str | None = Header(default=None)):
        if settings.inbound_token:
            supplied = (authorization or "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied, settings.inbound_token):
                raise HTTPException(401, "Frame Forge engine token required.")

    @app.get("/api/healthz")
    def health():
        return {
            "status": "ok",
            "engine": "Frame Forge AI",
            "version": __version__,
            "openrouter_key_configured": bool(settings.openrouter_api_key),
            "modes": {
                mode.value: {
                    "mockup_configured": settings.configured_for_mockup(mode),
                    "video_short_configured": settings.configured_for_video(mode, 10),
                    "video_medium_configured": settings.configured_for_video(mode, 20),
                    "video_long_configured": settings.configured_for_video(mode, 30),
                }
                for mode in ProcessingMode
            },
        }

    @app.get("/api/frameforge/capabilities", dependencies=[Depends(access)])
    def capabilities():
        return {
            "engine": "Frame Forge AI",
            "version": __version__,
            "provider": "OpenRouter",
            "template_counts": {"mockup": 3, "video": 3},
            "modes": [mode.value for mode in ProcessingMode],
            "video_duration_seconds": {"minimum": 10, "maximum": 30},
            "aspect_ratios": ["9:16", "16:9", "1:1", "4:5"],
            "accepted_sources": sorted(SOURCE_TYPES),
            "accepted_logos": ["image/png", "image/jpeg", "image/webp"],
            "exact_brand_overlay": {"mockup": True, "video": settings.video_postprocess_required},
            "storage": "ephemeral job files with automatic retention cleanup",
        }

    @app.get("/api/frameforge/templates", dependencies=[Depends(access)])
    def templates():
        return catalog()

    @app.get("/api/frameforge/templates/{template_id}/preview.svg")
    def template_preview(template_id: str):
        template = ALL_TEMPLATES.get(template_id)
        if template is None:
            raise FrameForgeError("TEMPLATE_NOT_FOUND", "Template preview not found.", 404)
        path = Path(__file__).parent / "static" / "templates" / template.preview_path
        if not path.is_file():
            raise FrameForgeError("PREVIEW_MISSING", "Template preview is unavailable.", 404)
        return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/frameforge/provider-assets/{job_id}/{token}.png", include_in_schema=False)
    def provider_asset(job_id: str, token: str):
        path = engine.provider_asset(job_id, token)
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    @app.post("/api/frameforge/jobs/mockup", status_code=202, dependencies=[Depends(access)])
    async def create_mockup(
        source: UploadFile = File(...),
        logo: UploadFile | None = File(default=None),
        options_json: str = Form(default="{}"),
    ):
        try:
            options = MockupOptions.model_validate_json(options_json)
        except ValidationError as exc:
            raise FrameForgeError("INVALID_OPTIONS", "Mockup options JSON is invalid.", 422) from exc
        source_payload = await _upload(source, settings.max_upload_bytes)
        logo_payload = await _upload(logo, settings.max_upload_bytes) if logo else None
        return engine.create_mockup(source_payload, logo_payload, options).public()

    @app.post("/api/frameforge/jobs/{mockup_job_id}/video", status_code=202, dependencies=[Depends(access)])
    def create_video(mockup_job_id: str, options: VideoOptions):
        return engine.create_video(mockup_job_id, options).public()

    @app.get("/api/frameforge/jobs/{job_id}", dependencies=[Depends(access)])
    def get_job(job_id: str):
        return engine.get(job_id).public()

    @app.post("/api/frameforge/jobs/{job_id}/cancel", dependencies=[Depends(access)])
    def cancel_job(job_id: str):
        return engine.cancel(job_id).public()

    @app.get("/api/frameforge/jobs/{job_id}/output", dependencies=[Depends(access)])
    def output(job_id: str):
        state, path = engine.output(job_id)
        return FileResponse(
            path,
            media_type=state.output_content_type or "application/octet-stream",
            filename=path.name,
            headers={"Cache-Control": "no-store"},
        )

    return app

