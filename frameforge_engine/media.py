from __future__ import annotations

import json
import re
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .errors import FrameForgeError
from .models import BrandDetails
from .openrouter import AssetInput


FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int, bold: bool = False):
    for candidate in FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


class MediaProcessor:
    def normalize_reference(self, source: AssetInput, destination: Path) -> AssetInput:
        try:
            if source.content_type == "application/pdf":
                self._pdf_to_png(source.path, destination)
            elif source.content_type == "image/svg+xml":
                self._svg_to_png(source.path, destination)
            elif source.content_type == "application/postscript":
                self._eps_to_png(source.path, destination)
            else:
                self._raster_to_png(source.path, destination)
        except FrameForgeError:
            raise
        except Exception as exc:
            raise FrameForgeError("SOURCE_NORMALIZATION_FAILED", "Input could not be converted into a safe visual reference.", 422) from exc
        return AssetInput(destination, "normalized-reference.png", "image/png")

    @staticmethod
    def _raster_to_png(source: Path, destination: Path) -> None:
        try:
            with Image.open(source) as opened:
                opened.seek(0)
                image = opened.convert("RGBA")
                image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
                image.save(destination, "PNG", optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            raise FrameForgeError("INVALID_IMAGE", "Input image could not be decoded.", 422) from exc

    @staticmethod
    def _pdf_to_png(source: Path, destination: Path) -> None:
        try:
            import fitz

            with fitz.open(source) as document:
                if document.page_count < 1:
                    raise FrameForgeError("INVALID_DOCUMENT", "PDF contains no pages.", 422)
                page = document.load_page(0)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
                image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")
                image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
                image.save(destination, "PNG", optimize=True)
        except FrameForgeError:
            raise
        except Exception as exc:
            raise FrameForgeError("INVALID_DOCUMENT", "PDF preview conversion failed.", 422) from exc

    @staticmethod
    def _svg_to_png(source: Path, destination: Path) -> None:
        data = source.read_bytes()
        lowered = data.lower()
        blocked = (b"<!doctype", b"<!entity", b"<script", b"<foreignobject", b"file://")
        external_reference = re.search(rb"(?:href|src)\s*=\s*['\"]\s*https?://", lowered)
        external_css = re.search(rb"url\s*\(\s*['\"]?\s*https?://", lowered)
        if any(value in lowered for value in blocked) or external_reference or external_css:
            raise FrameForgeError("UNSAFE_SVG", "SVG contains blocked active or external content.", 422)
        try:
            import cairosvg

            cairosvg.svg2png(bytestring=data, write_to=str(destination), output_width=2048)
        except Exception as exc:
            raise FrameForgeError("INVALID_DOCUMENT", "SVG preview conversion failed.", 422) from exc

    @staticmethod
    def _eps_to_png(source: Path, destination: Path) -> None:
        ghostscript = shutil.which("gs")
        if not ghostscript:
            raise FrameForgeError("GHOSTSCRIPT_UNAVAILABLE", "Ghostscript is required for EPS input.", 503)
        process = subprocess.run(
            [
                ghostscript,
                "-dSAFER",
                "-dBATCH",
                "-dNOPAUSE",
                "-dFirstPage=1",
                "-dLastPage=1",
                "-sDEVICE=pngalpha",
                "-r144",
                f"-sOutputFile={destination}",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if process.returncode != 0 or not destination.is_file():
            raise FrameForgeError("INVALID_DOCUMENT", "EPS preview conversion failed.", 422)
        MediaProcessor._raster_to_png(destination, destination.with_suffix(".normalized.png"))
        destination.with_suffix(".normalized.png").replace(destination)

    def brand_image(
        self,
        source: Path,
        destination: Path,
        brand: BrandDetails,
        logo_path: Path | None,
    ) -> str:
        try:
            with Image.open(source) as opened:
                image = opened.convert("RGBA")
        except (UnidentifiedImageError, OSError) as exc:
            raise FrameForgeError("GENERATED_IMAGE_INVALID", "Generated image could not be decoded.", 502) from exc

        overlay = self._overlay(image.size, brand, logo_path)
        Image.alpha_composite(image, overlay).convert("RGB").save(destination, "PNG", optimize=True)
        return "image/png"

    def brand_video(
        self,
        source: Path,
        destination: Path,
        brand: BrandDetails,
        logo_path: Path | None,
        required: bool,
        aspect_ratio: str = "",
    ) -> str:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            if required:
                raise FrameForgeError("FFMPEG_UNAVAILABLE", "FFmpeg is required for exact video branding.", 503)
            shutil.copyfile(source, destination)
            return "video/mp4"

        probe = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(source)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            stream = json.loads(probe.stdout)["streams"][0]
            size = (int(stream["width"]), int(stream["height"]))
        except Exception as exc:
            raise FrameForgeError("VIDEO_INVALID", "Generated video dimensions could not be read.", 502) from exc

        output_size = self._crop_size(size, aspect_ratio) if aspect_ratio else size
        overlay_path = destination.with_name("brand-overlay.png")
        self._overlay(output_size, brand, logo_path).save(overlay_path, "PNG", optimize=True)
        crop_filter = ""
        if output_size != size:
            crop_filter = f"crop={output_size[0]}:{output_size[1]}:(iw-{output_size[0]})/2:(ih-{output_size[1]})/2,"
        command = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-i",
            str(overlay_path),
            "-filter_complex",
            f"[0:v]{crop_filter}setsar=1[base];[base][1:v]overlay=0:0:format=auto[v]",
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(destination),
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        overlay_path.unlink(missing_ok=True)
        if process.returncode != 0 or not destination.is_file():
            raise FrameForgeError("VIDEO_BRANDING_FAILED", "Exact logo/contact compositing failed.", 502)
        return "video/mp4"

    @staticmethod
    def _crop_size(size: tuple[int, int], aspect_ratio: str) -> tuple[int, int]:
        try:
            width_ratio, height_ratio = (int(value) for value in aspect_ratio.split(":", 1))
            target = width_ratio / height_ratio
        except (ValueError, ZeroDivisionError):
            raise FrameForgeError("ASPECT_RATIO_INVALID", "Requested video aspect ratio is invalid.", 422)
        width, height = size
        if width / height > target:
            output = (int(height * target), height)
        else:
            output = (width, int(width / target))
        return (max(2, output[0] // 2 * 2), max(2, output[1] // 2 * 2))

    def _overlay(self, size: tuple[int, int], brand: BrandDetails, logo_path: Path | None) -> Image.Image:
        width, height = size
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        margin = max(16, width // 40)

        if logo_path and logo_path.is_file():
            try:
                with Image.open(logo_path) as opened:
                    logo = opened.convert("RGBA")
                target_width = min(width // 5, max(96, width // 8))
                scale = target_width / max(1, logo.width)
                logo = logo.resize((target_width, max(1, int(logo.height * scale))), Image.Resampling.LANCZOS)
                x = width - logo.width - margin
                y = margin
                shadow = Image.new("RGBA", logo.size, (0, 0, 0, 85))
                overlay.alpha_composite(shadow, (x + 3, y + 4))
                overlay.alpha_composite(logo, (x, y))
            except (UnidentifiedImageError, OSError):
                raise FrameForgeError("LOGO_INVALID", "Brand logo could not be decoded.", 422)

        lines = brand.lines()
        if lines:
            footer_height = min(height // 4, max(90, int(height * 0.12)))
            top = height - footer_height
            draw.rectangle((0, top, width, height), fill=(5, 10, 22, 205))
            accent = max(3, height // 500)
            draw.rectangle((0, top, width, top + accent), fill=(28, 220, 255, 230))
            max_size = max(12, min(width, height) // 34)
            available = footer_height - margin
            line_height = max(14, available // max(1, len(lines)))
            y = top + max(8, margin // 2)
            for index, line in enumerate(lines):
                font = _font(min(max_size, max(10, int(line_height * 0.62))), bold=index == 0)
                rendered = line
                while len(rendered) > 4 and draw.textbbox((0, 0), rendered, font=font)[2] > width - (margin * 2):
                    rendered = rendered[:-2]
                if rendered != line:
                    rendered = rendered.rstrip() + "…"
                draw.text((margin, y), rendered, font=font, fill=(255, 255, 255, 245))
                y += line_height
        return overlay

