import tempfile
import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from frameforge_engine.config import ModelPools, Settings
from frameforge_engine.errors import FrameForgeError
from frameforge_engine.models import BrandDetails, MockupOptions, ProcessingMode, VideoOptions
from frameforge_engine.openrouter import GeneratedMedia
from frameforge_engine.service import FrameForgeService, UploadPayload


def png(color=(20, 80, 140, 255)) -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (160, 240), color).save(stream, "PNG")
    return stream.getvalue()


def settings(root: Path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8000,
        inbound_token="secret",
        workspace=root,
        openrouter_api_key="or-key",
        openrouter_base_url="https://openrouter.example/api/v1",
        openrouter_site_url="https://myjersey.example",
        openrouter_app_name="Frame Forge Test",
        public_base_url="https://frameforge.example",
        asset_signing_secret="signing-secret",
        quality=ModelPools(
            analysis=("quality-analysis",),
            image=("quality-image",),
            video_short=("quality-video-short",),
            video_medium=("quality-video-medium",),
            video_long=("quality-video-long",),
        ),
        cost_effective=ModelPools(
            analysis=("cost-analysis",),
            image=("cost-image",),
            video_short=("cost-video-short",),
            video_medium=("cost-video-medium",),
            video_long=("cost-video-long",),
        ),
        quality_image_resolution="4K",
        cost_image_resolution="2K",
        quality_video_resolution="1080p",
        cost_video_resolution="720p",
        max_upload_bytes=5 * 1024 * 1024,
        max_output_bytes=50 * 1024 * 1024,
        max_workers=2,
        request_timeout_seconds=60,
        video_poll_seconds=0.01,
        retention_hours=24,
        output_hosts=(),
        video_postprocess_required=True,
    )


class FakeGateway:
    def __init__(self):
        self.analysis_models = None
        self.image_models = None
        self.video_models = None
        self.image_prompt = ""
        self.video_prompt = ""
        self.video_duration = None
        self.video_ratio = None

    def analyze(self, source, logo, models):
        assert source.path.is_file()
        assert logo is not None and logo.path.is_file()
        self.analysis_models = tuple(models)
        return {
            "asset_type": "jersey",
            "dominant_colors": ["navy", "cyan"],
            "materials": ["performance fabric"],
            "visible_text": ["10"],
            "brand_marks": ["crest"],
            "composition_notes": "front view",
            "preservation_requirements": ["logo", "number"],
            "recommended_background": "dark studio",
            "risk_flags": [],
        }, tuple(models)[0]

    def generate_image(self, source, logo, prompt, aspect_ratio, quality, models):
        self.image_models = tuple(models)
        self.image_prompt = prompt
        assert aspect_ratio == "9:16"
        return GeneratedMedia(png(), "image/png", tuple(models)[0])

    def generate_video(self, frame_url, prompt, aspect_ratio, duration_seconds, quality, models, cancel_check=None):
        assert frame_url.startswith("https://frameforge.example/api/frameforge/provider-assets/")
        self.video_models = tuple(models)
        self.video_prompt = prompt
        self.video_duration = duration_seconds
        self.video_ratio = aspect_ratio
        return GeneratedMedia(b"fake-mp4", "video/mp4", tuple(models)[0])


class FakeMedia:
    def __init__(self):
        self.image_brand = None
        self.video_brand = None

    def normalize_reference(self, source, destination):
        destination.write_bytes(source.path.read_bytes())
        return type(source)(destination, "normalized-reference.png", "image/png")

    def brand_image(self, source, destination, brand, logo_path):
        self.image_brand = brand
        destination.write_bytes(source.read_bytes())
        return "image/png"

    def brand_video(self, source, destination, brand, logo_path, required, aspect_ratio=""):
        self.video_brand = brand
        assert required is True
        destination.write_bytes(source.read_bytes())
        return "video/mp4"


def wait_terminal(service, job_id):
    for _ in range(200):
        state = service.get(job_id)
        if state.status in {"ready", "failed", "cancelled"}:
            return state
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def create_ready_mockup(service, mode=ProcessingMode.QUALITY):
    options = MockupOptions(
        template_id="mockup_luxury_float",
        mode=mode,
        brand=BrandDetails(
            brand_name="My Jersey",
            tagline="Built for champions",
            phone="+8801000000000",
            website="myjersey.example",
        ),
    )
    state = service.create_mockup(
        UploadPayload("design.png", png(), "image/png"),
        UploadPayload("logo.png", png((0, 255, 120, 255)), "image/png"),
        options,
    )
    return wait_terminal(service, state.job_id)


def test_quality_mockup_uses_template_analysis_and_exact_branding():
    with tempfile.TemporaryDirectory() as temp:
        gateway = FakeGateway()
        media = FakeMedia()
        service = FrameForgeService(settings(Path(temp)), gateway, media)
        state = create_ready_mockup(service)
        assert state.status == "ready"
        assert gateway.analysis_models == ("quality-analysis",)
        assert gateway.image_models == ("quality-image",)
        assert "Luxury" not in gateway.image_prompt or "ultra-realistic" in gateway.image_prompt
        assert "9:16" in gateway.image_prompt
        assert "+8801000000000" not in gateway.image_prompt
        assert media.image_brand.phone == "+8801000000000"
        assert service.output(state.job_id)[1].read_bytes() == png()
        service.close()


def test_cost_mode_uses_cost_model_pools():
    with tempfile.TemporaryDirectory() as temp:
        gateway = FakeGateway()
        service = FrameForgeService(settings(Path(temp)), gateway, FakeMedia())
        state = create_ready_mockup(service, ProcessingMode.COST_EFFECTIVE)
        assert state.status == "ready"
        assert gateway.analysis_models == ("cost-analysis",)
        assert gateway.image_models == ("cost-image",)
        service.close()


def test_video_30_seconds_selects_long_pool_and_inherits_brand():
    with tempfile.TemporaryDirectory() as temp:
        gateway = FakeGateway()
        media = FakeMedia()
        service = FrameForgeService(settings(Path(temp)), gateway, media)
        mockup = create_ready_mockup(service)
        video = service.create_video(
            mockup.job_id,
            VideoOptions(
                template_id="video_luxury_360",
                duration_seconds=30,
                aspect_ratio="16:9",
                mode=ProcessingMode.QUALITY,
            ),
        )
        completed = wait_terminal(service, video.job_id)
        assert completed.status == "ready"
        assert gateway.video_models == ("quality-video-long",)
        assert gateway.video_duration == 30
        assert gateway.video_ratio == "16:9"
        assert "Exact duration: 30 seconds" in gateway.video_prompt
        assert media.video_brand.brand_name == "My Jersey"
        service.close()


def test_video_requires_ready_mockup():
    with tempfile.TemporaryDirectory() as temp:
        service = FrameForgeService(settings(Path(temp)), FakeGateway(), FakeMedia())
        with pytest.raises(FrameForgeError) as raised:
            service.create_video("f" * 32, VideoOptions(template_id="video_luxury_360"))
        assert raised.value.code == "JOB_NOT_FOUND"
        service.close()


def test_rejects_unsupported_source_type_before_background_work():
    with tempfile.TemporaryDirectory() as temp:
        service = FrameForgeService(settings(Path(temp)), FakeGateway(), FakeMedia())
        with pytest.raises(FrameForgeError) as raised:
            service.create_mockup(
                UploadPayload("malware.exe", b"MZ", "application/x-msdownload"),
                None,
                MockupOptions(template_id="mockup_luxury_float"),
            )
        assert raised.value.code == "UNSUPPORTED_FILE_TYPE"
        service.close()

