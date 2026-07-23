"""Sticker image processing using Pillow + optional ffmpeg.

This replaces ``telegram_sticker_utils`` (which requires ImageMagick/wand
as a system dependency). Pillow is pure-Python and needs no system libraries.

- Static images (PNG/JPG/WebP/BMP/TIFF): processed with Pillow -> PNG output
- Animated GIF: first frame as static PNG (Pillow), OR full animation as
  WebM if ffmpeg is available
- Video (WebM/MP4/MOV/MKV): converted to WebM via ffmpeg (optional)

If ffmpeg is missing, animated/video stickers fail with a clear message.
Static PNG/JPG stickers always work — no system dependencies needed.
"""

from __future__ import annotations

import io
import pathlib
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image

StickerFormat = Literal["static", "animated"]

# File extensions that are definitely static images
_STATIC_EXTS: set[str] = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
# File extensions that may need ffmpeg conversion
_VIDEO_EXTS: set[str] = {".gif", ".webm", ".mp4", ".mov", ".mkv", ".avi", ".m4v"}


@dataclass
class ProcessedSticker:
    """Result of processing a sticker file."""

    data: bytes
    sticker_type: StickerFormat  # "static" or "animated" — used as Telegram API format
    emojis: list[str] = field(default_factory=list)


def _has_ffmpeg() -> bool:
    """Check if ffmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None


def _resize_to_sticker(img: Image.Image, scale: int, master_edge: str) -> Image.Image:
    """Resize image so the master edge == scale, other edge <= scale (aspect preserved)."""
    w, h = img.size

    if master_edge == "width":
        # Make width = scale (if width >= height) or height = scale (if height > width)
        if w >= h:
            new_w = scale
            new_h = max(1, round(scale * h / w))
        else:
            new_h = scale
            new_w = max(1, round(scale * w / h))
    else:  # "height"
        if h >= w:
            new_h = scale
            new_w = max(1, round(scale * w / h))
        else:
            new_w = scale
            new_h = max(1, round(scale * h / w))

    # Never upscale beyond original — Telegram doesn't want upscaled stickers.
    if new_w > w or new_h > h:
        new_w = min(new_w, w)
        new_h = min(new_h, h)

    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _process_static(
    input_path: str,
    scale: int,
    master_edge: str = "width",
) -> ProcessedSticker:
    """Process a static image into a PNG sticker using Pillow."""
    img = Image.open(input_path)

    # Handle transparency: convert to RGBA for proper alpha channel.
    if img.mode not in ("RGBA", "RGB"):
        img = img.convert("RGBA")

    img = _resize_to_sticker(img, scale, master_edge)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()

    # Telegram static stickers must be <= 512 KB.
    if len(data) > 512 * 1024:
        # Re-save with less optimization / lower quality.
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False, compress_level=1)
        data = buf.getvalue()

    return ProcessedSticker(data=data, sticker_type="static", emojis=[])


def _gif_is_animated(path: str) -> bool:
    """Check if a GIF file has multiple frames (i.e. is animated)."""
    try:
        img = Image.open(path)
        n_frames = getattr(img, "n_frames", 1)
        return n_frames > 1
    except Exception:  # noqa: BLE001
        return False


def _process_animated(input_path: str, scale: int) -> ProcessedSticker:
    """Convert a video/animated file to WebM using ffmpeg.

    Telegram animated stickers: 256x256, WebM (VP9), <= 256 KB, <= 10s.
    """
    if not _has_ffmpeg():
        raise RuntimeError(
            "ffmpeg is not installed. Animated/video stickers (GIF, WebM, MP4, MOV) "
            "need ffmpeg. Static PNG/JPG stickers work without it.\n"
            "Download ffmpeg from: https://ffmpeg.org/download.html"
        )

    # Animated stickers use 256 (not 512) as the target edge.
    anim_scale = 256 if scale >= 512 else scale

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"scale={anim_scale}:{anim_scale}:force_original_aspect_ratio=decrease"
               f":flags=lanczos,format=yuva420p",
        "-c:v", "libvpx-vp9",
        "-b:v", "200k",
        "-maxrate", "256k",
        "-bufsize", "256k",
        "-t", "10",
        "-an",
        "-f", "webm",
        "-loop", "0",
        "-",  # output to stdout
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timed out after 120s processing {input_path}") from e

    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg failed to convert {input_path}:\n{stderr}")

    return ProcessedSticker(data=result.stdout, sticker_type="animated", emojis=[])


class ImageProcessor:
    """Drop-in replacement for ``telegram_sticker_utils.ImageProcessor``.

    Uses Pillow (no system deps) for static images, ffmpeg (optional) for video.
    """

    @staticmethod
    def make_sticker(
        *,
        input_name: str,
        input_data: str,
        scale: int = 512,
        master_edge: str = "width",
    ) -> ProcessedSticker:
        """Process a local file into sticker-ready bytes.

        :param input_name: file stem (used for emoji extraction by caller)
        :param input_data: path to the local file
        :param scale: target edge size (512 for regular, 100 for custom_emoji)
        :param master_edge: "width" or "height"
        :raises RuntimeError: if ffmpeg is needed but not found
        :raises ValueError: if the file format is unsupported
        """
        path = pathlib.Path(input_data)
        if not path.is_file():
            raise FileNotFoundError(f"Sticker file not found: {path}")

        ext = path.suffix.lower()

        # Static image — always works with Pillow.
        if ext in _STATIC_EXTS:
            return _process_static(str(path), scale, master_edge)

        # GIF — check if animated.
        if ext == ".gif":
            if _gif_is_animated(str(path)):
                # Animated GIF -> try WebM via ffmpeg.
                try:
                    return _process_animated(str(path), scale)
                except RuntimeError:
                    # If ffmpeg fails, fall back to first frame as static PNG.
                    pass
            # Static GIF -> PNG.
            return _process_static(str(path), scale, master_edge)

        # Video formats -> ffmpeg.
        if ext in _VIDEO_EXTS:
            return _process_animated(str(path), scale)

        # Unknown extension — try Pillow as a last resort.
        try:
            return _process_static(str(path), scale, master_edge)
        except Exception as e:
            raise ValueError(
                f"Unsupported file format '{ext}' for {path.name}: {e}"
            ) from e


__all__ = ["ImageProcessor", "ProcessedSticker", "StickerFormat"]
