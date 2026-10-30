from pathlib import Path

import pytest

from frameforge_engine.config import Settings
from frameforge_engine.models import ProcessingMode


def test_public_bind_requires_engine_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FRAMEFORGE_HOST", "0.0.0.0")
    monkeypatch.setenv("FRAMEFORGE_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("FRAMEFORGE_ENGINE_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        Settings.from_env()


def test_environment_parses_mode_specific_model_pools(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FRAMEFORGE_HOST", "127.0.0.1")
    monkeypatch.setenv("FRAMEFORGE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("FRAMEFORGE_PUBLIC_BASE_URL", "https://frameforge.example")
    monkeypatch.setenv("FRAMEFORGE_ASSET_SIGNING_SECRET", "secret")
    monkeypatch.setenv("FRAMEFORGE_QUALITY_ANALYSIS_MODELS", "analysis-a,analysis-b")
    monkeypatch.setenv("FRAMEFORGE_QUALITY_IMAGE_MODELS", "image-a")
    monkeypatch.setenv("FRAMEFORGE_QUALITY_VIDEO_LONG_MODELS", "video-long")
    settings = Settings.from_env()
    assert settings.quality.analysis == ("analysis-a", "analysis-b")
    assert settings.configured_for_mockup(ProcessingMode.QUALITY) is True
    assert settings.configured_for_video(ProcessingMode.QUALITY, 30) is True

