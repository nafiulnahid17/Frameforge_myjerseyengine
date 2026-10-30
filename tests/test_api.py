import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from frameforge_engine.api import create_app
from frameforge_engine.config import ModelPools, Settings


class StubService:
    def start(self):
        pass

    def close(self):
        pass


def settings(root: Path) -> Settings:
    pools = ModelPools(("analysis",), ("image",), ("video-10",), ("video-20",), ("video-30",))
    return Settings(
        host="127.0.0.1",
        port=8000,
        inbound_token="engine-secret",
        workspace=root,
        openrouter_api_key="openrouter-secret",
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
        max_upload_bytes=1024,
        max_output_bytes=1024,
        max_workers=1,
        request_timeout_seconds=30,
        video_poll_seconds=0.01,
        retention_hours=24,
        output_hosts=(),
        video_postprocess_required=True,
    )


def test_health_is_public_but_private_catalog_requires_token():
    with tempfile.TemporaryDirectory() as temp:
        app = create_app(settings(Path(temp)), StubService())
        with TestClient(app) as client:
            health = client.get("/api/healthz")
            assert health.status_code == 200
            assert "openrouter-secret" not in health.text
            assert client.get("/api/frameforge/templates").status_code == 401
            catalog = client.get(
                "/api/frameforge/templates",
                headers={"Authorization": "Bearer engine-secret"},
            )
            assert catalog.status_code == 200
            assert len(catalog.json()["mockup"]) == 3
            assert len(catalog.json()["video"]) == 3


def test_template_previews_are_public_static_svg():
    with tempfile.TemporaryDirectory() as temp:
        app = create_app(settings(Path(temp)), StubService())
        with TestClient(app) as client:
            response = client.get("/api/frameforge/templates/mockup_luxury_float/preview.svg")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("image/svg+xml")
            assert b"LUXURY 3D FLOAT" in response.content


def test_mockup_endpoint_rejects_bad_options_before_submission():
    with tempfile.TemporaryDirectory() as temp:
        app = create_app(settings(Path(temp)), StubService())
        with TestClient(app) as client:
            response = client.post(
                "/api/frameforge/jobs/mockup",
                headers={"Authorization": "Bearer engine-secret"},
                files={"source": ("design.png", b"not-used", "image/png")},
                data={"options_json": "not-json"},
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "INVALID_OPTIONS"


