from __future__ import annotations

import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .errors import FrameForgeError
from .media import MediaProcessor
from .models import JobKind, JobState, MockupOptions, ProcessingMode, VideoOptions
from .openrouter import AssetInput, GeneratedMedia, OpenRouterGateway
from .prompts import build_mockup_prompt, build_video_prompt
from .signing import create_asset_token, verify_asset_token
from .store import JobStore
from .templates import get_template


SOURCE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "application/postscript": ".eps",
    "image/vnd.adobe.photoshop": ".psd",
}
LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class UploadPayload:
    filename: str
    content: bytes
    content_type: str


class FrameForgeService:
    def __init__(
        self,
        settings: Settings,
        gateway: OpenRouterGateway | None = None,
        media: MediaProcessor | None = None,
    ):
        self.settings = settings
        self.store = JobStore(settings.workspace)
        self.gateway = gateway or OpenRouterGateway(settings)
        self.media = media or MediaProcessor()
        self.executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="frameforge")
        self.lock = threading.RLock()
        self.futures: dict[str, object] = {}

    def start(self) -> None:
        self.store.cleanup(self.settings.retention_hours)
        self.store.recover_interrupted()

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _submit(self, job_id: str, function: Callable, *args) -> None:
        with self.lock:
            future = self.executor.submit(function, job_id, *args)
            self.futures[job_id] = future

            def completed(_future):
                with self.lock:
                    self.futures.pop(job_id, None)

            future.add_done_callback(completed)

    @staticmethod
    def _clean_content_type(value: str) -> str:
        return value.split(";", 1)[0].strip().lower()

    @staticmethod
    def _verify_raster(content: bytes) -> None:
        try:
            from io import BytesIO

            with Image.open(BytesIO(content)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise FrameForgeError("INVALID_IMAGE", "Uploaded image is invalid or unsupported.", 422) from exc

    def _save_upload(self, job_id: str, name: str, payload: UploadPayload, logo: bool = False) -> AssetInput:
        content_type = self._clean_content_type(payload.content_type)
        allowed = LOGO_TYPES if logo else SOURCE_TYPES
        suffix = allowed.get(content_type)
        if suffix is None:
            label = "logo" if logo else "source"
            raise FrameForgeError("UNSUPPORTED_FILE_TYPE", f"Unsupported {label} file type: {content_type or 'unknown'}.", 415)
        if not payload.content or len(payload.content) > self.settings.max_upload_bytes:
            raise FrameForgeError("UPLOAD_SIZE_INVALID", "Upload is empty or exceeds the configured limit.", 413)
        if content_type.startswith("image/") and content_type != "image/svg+xml":
            self._verify_raster(payload.content)
        if content_type == "application/pdf" and not payload.content.startswith(b"%PDF-"):
            raise FrameForgeError("INVALID_DOCUMENT", "Uploaded PDF is invalid.", 422)
        if content_type == "application/postscript" and not payload.content.startswith(b"%!PS"):
            raise FrameForgeError("INVALID_DOCUMENT", "Uploaded EPS/PostScript file is invalid.", 422)
        if content_type == "image/vnd.adobe.photoshop" and not payload.content.startswith(b"8BPS"):
            raise FrameForgeError("INVALID_DOCUMENT", "Uploaded PSD file is invalid.", 422)
        path = self.store.job_dir(job_id) / f"{name}{suffix}"
        path.write_bytes(payload.content)
        return AssetInput(path, Path(payload.filename).name[:160] or path.name, content_type)

    def create_mockup(
        self,
        source: UploadPayload,
        logo: UploadPayload | None,
        options: MockupOptions,
    ) -> JobState:
        self.store.cleanup(self.settings.retention_hours)
        get_template(options.template_id, "mockup")
        if not self.settings.configured_for_mockup(options.mode):
            raise FrameForgeError("MODE_NOT_CONFIGURED", f"{options.mode.value} mockup models are not configured.", 503)
        job_id = uuid.uuid4().hex
        state = self.store.create(JobState(
            job_id=job_id,
            kind=JobKind.MOCKUP,
            mode=options.mode,
            template_id=options.template_id,
            aspect_ratio=options.aspect_ratio,
            brand=options.brand,
            has_logo=logo is not None,
        ))
        try:
            source_asset = self._save_upload(job_id, "source", source)
            logo_asset = self._save_upload(job_id, "logo", logo, logo=True) if logo else None
        except Exception:
            shutil.rmtree(self.store.job_dir(job_id), ignore_errors=True)
            raise
        self._submit(job_id, self._run_mockup, source_asset, logo_asset, options)
        return state

    def _run_mockup(
        self,
        job_id: str,
        source: AssetInput,
        logo: AssetInput | None,
        options: MockupOptions,
    ) -> None:
        try:
            pools = self.settings.pools_for(options.mode)
            self.store.update(job_id, status="processing", stage="analyzing", progress=12)
            normalized = self.media.normalize_reference(
                source,
                self.store.job_dir(job_id) / "normalized-reference.png",
            )
            analysis, analysis_model = self.gateway.analyze(normalized, logo, pools.analysis)
            if self._cancelled(job_id):
                return
            template = get_template(options.template_id, "mockup")
            prompt = build_mockup_prompt(
                template,
                analysis,
                options.brand,
                options.aspect_ratio.value,
                options.mode,
                options.style_notes,
            )
            self.store.update(
                job_id,
                stage="generating_mockup",
                progress=36,
                analysis=analysis,
                prompt=prompt,
                selected_model=analysis_model,
            )
            generated = self.gateway.generate_image(
                normalized,
                logo,
                prompt,
                options.aspect_ratio.value,
                options.mode == ProcessingMode.QUALITY,
                pools.image,
            )
            if self._cancelled(job_id):
                return
            directory = self.store.job_dir(job_id)
            raw = directory / "generated-image.bin"
            raw.write_bytes(generated.content)
            self.store.update(job_id, stage="applying_exact_branding", progress=86, selected_model=generated.model)
            output = directory / "mockup.png"
            content_type = self.media.brand_image(raw, output, options.brand, logo.path if logo else None)
            raw.unlink(missing_ok=True)
            self.store.update(
                job_id,
                status="ready",
                stage="complete",
                progress=100,
                output_name=output.name,
                output_content_type=content_type,
            )
        except FrameForgeError as exc:
            self._fail(job_id, exc)
        except Exception:
            self._fail(job_id, FrameForgeError("INTERNAL_ERROR", "Frame Forge could not complete the mockup.", 500))

    def create_video(self, mockup_job_id: str, options: VideoOptions) -> JobState:
        self.store.cleanup(self.settings.retention_hours)
        template = get_template(options.template_id, "video")
        del template
        source_state = self.store.get(mockup_job_id)
        if source_state.kind != JobKind.MOCKUP or source_state.status != "ready":
            raise FrameForgeError("MOCKUP_NOT_READY", "An approved completed mockup is required before video generation.", 409)
        if not self.settings.configured_for_video(options.mode, options.duration_seconds):
            raise FrameForgeError("MODE_NOT_CONFIGURED", f"{options.mode.value} video models are not configured for this duration.", 503)

        job_id = uuid.uuid4().hex
        state = self.store.create(JobState(
            job_id=job_id,
            kind=JobKind.VIDEO,
            mode=options.mode,
            template_id=options.template_id,
            aspect_ratio=options.aspect_ratio,
            duration_seconds=options.duration_seconds,
            source_job_id=mockup_job_id,
            analysis=source_state.analysis,
            brand=source_state.brand,
            has_logo=source_state.has_logo,
        ))
        destination = self.store.job_dir(job_id)
        source_path = self.store.output_path(source_state)
        mockup_path = destination / "approved-mockup.png"
        shutil.copyfile(source_path, mockup_path)
        logo_path = self._find_logo(mockup_job_id)
        copied_logo = None
        if logo_path:
            copied_logo = destination / ("logo" + logo_path.suffix.lower())
            shutil.copyfile(logo_path, copied_logo)
        self._submit(job_id, self._run_video, copied_logo, options, source_state)
        return state

    def _run_video(
        self,
        job_id: str,
        logo_path: Path | None,
        options: VideoOptions,
        source_state: JobState,
    ) -> None:
        try:
            pools = self.settings.pools_for(options.mode)
            models = pools.video_for(options.duration_seconds)
            template = get_template(options.template_id, "video")
            prompt = build_video_prompt(
                template,
                source_state.analysis or {},
                source_state.brand,
                options.aspect_ratio.value,
                options.duration_seconds,
                options.mode,
                options.style_notes,
            )
            self.store.update(job_id, status="processing", stage="generating_video", progress=18, prompt=prompt)
            expires_at = int(time.time()) + self.settings.request_timeout_seconds + 900
            token = create_asset_token(job_id, self.settings.asset_signing_secret, expires_at)
            frame_url = f"{self.settings.public_base_url}/api/frameforge/provider-assets/{job_id}/{token}.png"
            provider_ratio = "3:4" if options.aspect_ratio.value == "4:5" else options.aspect_ratio.value
            generated = self.gateway.generate_video(
                frame_url,
                prompt,
                provider_ratio,
                options.duration_seconds,
                options.mode == ProcessingMode.QUALITY,
                models,
                cancel_check=lambda: self._cancelled(job_id),
            )
            if self._cancelled(job_id):
                return
            directory = self.store.job_dir(job_id)
            raw = directory / "generated-video.bin"
            raw.write_bytes(generated.content)
            self.store.update(job_id, stage="applying_exact_branding", progress=88, selected_model=generated.model)
            output = directory / "video.mp4"
            content_type = self.media.brand_video(
                raw,
                output,
                source_state.brand,
                logo_path,
                self.settings.video_postprocess_required,
                options.aspect_ratio.value,
            )
            raw.unlink(missing_ok=True)
            self.store.update(
                job_id,
                status="ready",
                stage="complete",
                progress=100,
                output_name=output.name,
                output_content_type=content_type,
            )
        except FrameForgeError as exc:
            self._fail(job_id, exc)
        except Exception:
            self._fail(job_id, FrameForgeError("INTERNAL_ERROR", "Frame Forge could not complete the video.", 500))

    def _find_logo(self, job_id: str) -> Path | None:
        directory = self.store.job_dir(job_id)
        for suffix in LOGO_TYPES.values():
            path = directory / ("logo" + suffix)
            if path.is_file():
                return path
        return None

    def _cancelled(self, job_id: str) -> bool:
        return self.store.get(job_id).status == "cancelled"

    def _fail(self, job_id: str, error: FrameForgeError) -> None:
        if self._cancelled(job_id):
            return
        self.store.update(
            job_id,
            status="failed",
            stage="failed",
            error={"code": error.code, "message": str(error)},
        )

    def get(self, job_id: str) -> JobState:
        return self.store.get(job_id)

    def cancel(self, job_id: str) -> JobState:
        state = self.store.get(job_id)
        if state.status not in {"queued", "processing"}:
            raise FrameForgeError("JOB_NOT_CANCELLABLE", "This job can no longer be cancelled.", 409)
        return self.store.update(job_id, status="cancelled", stage="cancelled")

    def output(self, job_id: str) -> tuple[JobState, Path]:
        state = self.store.get(job_id)
        if state.status != "ready":
            raise FrameForgeError("OUTPUT_NOT_READY", "Job output is not ready.", 409)
        return state, self.store.output_path(state)

    def provider_asset(self, job_id: str, token: str) -> Path:
        if not verify_asset_token(job_id, token, self.settings.asset_signing_secret):
            raise FrameForgeError("ASSET_LINK_INVALID", "Provider asset link is invalid or expired.", 404)
        state = self.store.get(job_id)
        if state.kind != JobKind.VIDEO or state.status not in {"queued", "processing"}:
            raise FrameForgeError("ASSET_LINK_INVALID", "Provider asset link is unavailable.", 404)
        path = self.store.job_dir(job_id) / "approved-mockup.png"
        if not path.is_file():
            raise FrameForgeError("ASSET_LINK_INVALID", "Provider asset is unavailable.", 404)
        return path

