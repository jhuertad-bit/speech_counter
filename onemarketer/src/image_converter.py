"""Conversión de imágenes raster hacia WebP o AVIF para reducir peso en GCS."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
})

OUTPUT_FORMATS = frozenset({"webp", "avif"})


def normalize_extension(file_name: str) -> str:
    _, ext = os.path.splitext(file_name.lower())
    return ext


def output_extension(output_format: str) -> str:
    fmt = (output_format or "webp").lower()
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(f"output_format inválido: {output_format} (use webp o avif)")
    return f".{fmt}"


def optimized_file_name(storage_file_name: str, output_format: str) -> str:
    base, _ = os.path.splitext(storage_file_name)
    return f"{base}{output_extension(output_format)}"


def is_supported_image(file_name: str, supported_extensions: list[str]) -> bool:
    ext = normalize_extension(file_name)
    normalized = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in supported_extensions]
    return ext in normalized


def is_image_for_optimize(
    mime: str | None,
    file_name: str | None = None,
    media_type: str | None = None,
) -> bool:
    if media_type == "image":
        return True
    if mime and mime.lower().startswith("image/"):
        return True
    if file_name:
        ext = normalize_extension(file_name)
        if ext in IMAGE_SOURCE_EXTENSIONS or ext in {".webp", ".avif"}:
            return mime is None or mime.lower().startswith("image/")
    return False


def _is_animated_gif(path: str) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return getattr(img, "is_animated", False) and img.n_frames > 1
    except Exception:
        return False


def _convert_with_pillow(
    input_path: str,
    output_path: str,
    output_format: str,
    quality: int,
) -> dict[str, Any]:
    from PIL import Image, ImageOps

    with Image.open(input_path) as img:
        animated = getattr(img, "is_animated", False) and img.n_frames > 1
        if animated:
            raise ValueError("GIF animado no soportado para optimización")

        img = ImageOps.exif_transpose(img)
        width, height = img.size

        fmt = output_format.lower()
        if fmt == "webp":
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            save_kwargs: dict[str, Any] = {"quality": quality, "method": 6}
            img.save(output_path, "WEBP", **save_kwargs)
        elif fmt == "avif":
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.save(output_path, "AVIF", quality=quality)
        else:
            raise ValueError(f"Formato no soportado: {output_format}")

    return {"method": "pillow", "width": width, "height": height}


def _convert_with_ffmpeg(
    input_path: str,
    output_path: str,
    output_format: str,
    quality: int,
    timeout: int,
) -> dict[str, Any]:
    fmt = output_format.lower()
    if fmt == "webp":
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", input_path,
            "-c:v", "libwebp",
            "-quality", str(quality),
            output_path,
        ]
    elif fmt == "avif":
        crf = max(18, min(45, int(52 - quality / 2.5)))
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", input_path,
            "-c:v", "libaom-av1",
            "-still_picture", "1",
            "-crf", str(crf),
            output_path,
        ]
    else:
        raise ValueError(f"Formato no soportado: {output_format}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg image conversion failed")
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("salida de imagen vacía")

    return {"method": "ffmpeg", "width": None, "height": None}


def convert_image(
    input_path: str,
    output_path: str,
    file_name: str,
    image_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Convierte imagen a WebP o AVIF. Retorna metadata de conversión."""
    output_format = (image_cfg.get("output_format") or "webp").lower()
    quality = int(image_cfg.get("quality", 82))
    timeout = int(image_cfg.get("ffmpeg_timeout_seconds", 120))
    supported = image_cfg.get(
        "supported_extensions",
        list(IMAGE_SOURCE_EXTENSIONS),
    )
    convert_animated_gif = image_cfg.get("convert_animated_gif", False)

    if not is_supported_image(file_name, supported):
        raise ValueError(f"Extensión de imagen no soportada: {file_name}")

    ext = normalize_extension(file_name)
    if ext == output_extension(output_format):
        raise ValueError("ALREADY_OPTIMIZED")

    if ext == ".gif" and not convert_animated_gif and _is_animated_gif(input_path):
        raise ValueError("GIF animado omitido (convert_animated_gif=false)")

    source_size = os.path.getsize(input_path)
    meta: dict[str, Any]

    try:
        meta = _convert_with_pillow(input_path, output_path, output_format, quality)
    except Exception as pillow_err:
        logger.warning("Pillow falló (%s), probando ffmpeg", pillow_err)
        if os.path.exists(output_path):
            os.remove(output_path)
        meta = _convert_with_ffmpeg(input_path, output_path, output_format, quality, timeout)

    output_size = os.path.getsize(output_path)
    saved_pct = round((1 - output_size / source_size) * 100, 1) if source_size else 0.0

    return {
        "output_format": output_format,
        "quality": quality,
        "method": meta.get("method"),
        "source_extension": ext,
        "source_file_size_bytes": source_size,
        "width": meta.get("width"),
        "height": meta.get("height"),
        "bytes_saved": max(0, source_size - output_size),
        "compression_ratio_pct": saved_pct,
    }
