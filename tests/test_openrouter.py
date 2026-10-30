import base64
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from frameforge_engine.config import ModelPools, Settings
from frameforge_engine.errors import FrameForgeError
from frameforge_engine.openrouter import AssetInput, OpenRouterGateway


def png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (8, 8), "cyan").save(stream, "PNG")
    return stream.getvalue()


def settings(root: Path) -> Settings:
    pools = ModelPools(("analysis",), ("image",), ("short",), ("medium",), ("long",))
    return Settings(
        host="127.0.0.1",
        port=8000,
        inbound_token="token",
        workspace=root,
        openrouter_api_key="key",
        openrouter_base_url="https://openrouter.example/api/v1",
        openrouter_site_url="",
        openrouter_app_name="test",
        public_base_url="https://frameforge.example",
        asset_signing_secret="signing-secret",
        quality=pools,
        cost_effective=pools,
        quality_image_resolution="4K",
        cost_image_resolution="2K",
        quality_video_resolution="1080p",
        cost_video_resolution="720p",
        max_upload_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_workers=1,
        request_timeout_seconds=60,
        video_poll_seconds=0.01,
        retention_hours=1,
        output_hosts=("media.example",),
        video_postprocess_required=True,
    )


class ResponseGateway(OpenRouterGateway):
    response = {}

    def _request_models(self, models, payload, operation, endpoint):
        self.last_payload = payload
        self.last_endpoint = endpoint
        return self.response, tuple(models)[0]


def test_analysis_uses_untrusted_file_guard_and_parses_json():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source_path = root / "source.png"
        source_path.write_bytes(png())
        gateway = ResponseGateway(settings(root))
        gateway.response = {
            "choices": [{"message": {"content": '{"asset_type":"jersey","risk_flags":[]}'}}]
        }
        analysis, model = gateway.analyze(AssetInput(source_path, "source.png", "image/png"), None, ("analysis",))
        assert analysis["asset_type"] == "jersey"
        assert model == "analysis"
        assert "untrusted visual content" in gateway.last_payload["messages"][0]["content"][0]["text"]


def test_image_and_video_data_urls_are_decoded_without_remote_fetch():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source_path = root / "source.png"
        source_path.write_bytes(png())
        asset = AssetInput(source_path, "source.png", "image/png")
        gateway = ResponseGateway(settings(root))
        gateway.response = {"data": [{"b64_json": base64.b64encode(png()).decode(), "media_type": "image/png"}]}
        image = gateway.generate_image(asset, None, "prompt", "9:16", True, ("image",))
        assert image.content.startswith(b"\x89PNG")
        assert image.model == "image"
        assert gateway.last_endpoint == "images"
        assert gateway.last_payload["resolution"] == "4K"

        video_url = "data:video/mp4;base64," + base64.b64encode(b"video-bytes").decode()
        gateway.response = {"id": "video-job", "status": "completed", "polling_url": "/api/v1/videos/video-job", "urls": [video_url]}
        video = gateway.generate_video("https://frameforge.example/frame.png", "prompt", "16:9", 20, False, ("medium",))
        assert video.content == b"video-bytes"
        assert gateway.last_endpoint == "videos"
        assert gateway.last_payload["duration"] == 20
        assert gateway.last_payload["resolution"] == "720p"


def test_media_host_allowlist_and_missing_media_fail_closed():
    with tempfile.TemporaryDirectory() as temp:
        gateway = ResponseGateway(settings(Path(temp)))
        assert gateway._host_allowed("cdn.media.example") is True
        assert gateway._host_allowed("127.0.0.1") is False
        gateway.response = {"data": []}
        asset_path = Path(temp) / "source.png"
        asset_path.write_bytes(png())
        with pytest.raises(FrameForgeError) as raised:
            gateway.generate_image(AssetInput(asset_path, "source.png", "image/png"), None, "prompt", "1:1", True, ("image",))
        assert raised.value.code == "MEDIA_MISSING"

