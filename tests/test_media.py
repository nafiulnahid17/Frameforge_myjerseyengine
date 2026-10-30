import tempfile
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from frameforge_engine.errors import FrameForgeError
from frameforge_engine.media import MediaProcessor
from frameforge_engine.models import BrandDetails
from frameforge_engine.openrouter import AssetInput


def image(path: Path, size=(640, 960), color=(20, 40, 80, 255)):
    Image.new("RGBA", size, color).save(path, "PNG")


def test_image_branding_preserves_dimensions_and_adds_exact_footer():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "source.png"
        logo = root / "logo.png"
        output = root / "output.png"
        image(source)
        image(logo, (120, 60), (0, 255, 120, 255))
        content_type = MediaProcessor().brand_image(
            source,
            output,
            BrandDetails(brand_name="My Jersey", phone="+8801000000000"),
            logo,
        )
        assert content_type == "image/png"
        with Image.open(output) as branded:
            assert branded.size == (640, 960)
            assert branded.getpixel((10, 950)) != (20, 40, 80)


def test_video_requires_ffmpeg_when_exact_branding_is_required(monkeypatch):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "raw.mp4"
        destination = root / "final.mp4"
        source.write_bytes(b"video")
        monkeypatch.setattr("frameforge_engine.media.shutil.which", lambda _name: None)
        with pytest.raises(FrameForgeError) as raised:
            MediaProcessor().brand_video(source, destination, BrandDetails(), None, True)
        assert raised.value.code == "FFMPEG_UNAVAILABLE"
        assert MediaProcessor().brand_video(source, destination, BrandDetails(), None, False) == "video/mp4"
        assert destination.read_bytes() == b"video"


def test_normalizes_raster_svg_and_pdf_references():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        processor = MediaProcessor()
        raster = root / "source.png"
        image(raster, (320, 200))
        normalized = processor.normalize_reference(
            AssetInput(raster, raster.name, "image/png"),
            root / "raster-normalized.png",
        )
        assert normalized.content_type == "image/png"
        assert normalized.path.is_file()

        svg = root / "source.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><rect width="100" height="50" fill="cyan"/></svg>')
        assert processor.normalize_reference(
            AssetInput(svg, svg.name, "image/svg+xml"),
            root / "svg-normalized.png",
        ).path.is_file()

        import fitz

        pdf = root / "source.pdf"
        document = fitz.open()
        page = document.new_page(width=200, height=100)
        page.draw_rect(page.rect, color=(0, 1, 1), fill=(0, 1, 1))
        document.save(pdf)
        document.close()
        assert processor.normalize_reference(
            AssetInput(pdf, pdf.name, "application/pdf"),
            root / "pdf-normalized.png",
        ).path.is_file()


def test_rejects_svg_with_external_content():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        svg = root / "unsafe.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/a.png"/></svg>')
        with pytest.raises(FrameForgeError) as raised:
            MediaProcessor().normalize_reference(
                AssetInput(svg, svg.name, "image/svg+xml"),
                root / "output.png",
            )
        assert raised.value.code == "UNSAFE_SVG"


def test_real_ffmpeg_branding_pipeline_creates_playable_mp4():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "raw.mp4"
        output = root / "branded.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x180:d=0.3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        assert MediaProcessor().brand_video(
            source,
            output,
            BrandDetails(brand_name="My Jersey", website="example.com"),
            None,
            True,
            "4:5",
        ) == "video/mp4"
        assert output.stat().st_size > 1000
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(output)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert probe.stdout.strip() == "144x180"


