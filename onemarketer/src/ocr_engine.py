"""Extracción de texto (OCR) desde imágenes y PDFs vía Vision API + PyMuPDF."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_OCR_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".avif",
})

PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


def normalize_extension(file_name: str) -> str:
    _, ext = os.path.splitext(file_name.lower())
    return ext


def is_pdf(file_name: str, mime: str | None = None) -> bool:
    if mime and "pdf" in mime.lower():
        return True
    return normalize_extension(file_name) in PDF_EXTENSIONS


def is_ocr_candidate(
    mime: str | None,
    file_name: str | None = None,
    media_type: str | None = None,
) -> bool:
    if is_pdf(file_name or "", mime):
        return True
    if media_type == "image":
        return True
    if media_type == "document" and mime and "pdf" in mime.lower():
        return True
    if mime and mime.lower().startswith("image/"):
        return True
    if file_name:
        ext = normalize_extension(file_name)
        if ext in IMAGE_OCR_EXTENSIONS:
            return True
    return False


def _avg_confidence(full_text_annotation: Any) -> float | None:
    scores: list[float] = []
    for page in getattr(full_text_annotation, "pages", []) or []:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    if word.confidence:
                        scores.append(float(word.confidence))
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _vision_client():
    from google.cloud import vision

    return vision.ImageAnnotatorClient()


def _vision_image_from_path(path: str) -> Any:
    from google.cloud import vision

    with open(path, "rb") as handle:
        content = handle.read()
    return vision.Image(content=content)


def _vision_image_from_gcs(gcs_uri: str) -> Any:
    from google.cloud import vision

    image = vision.Image()
    image.source.image_uri = gcs_uri
    return image


def extract_text_vision(
    *,
    local_path: str | None = None,
    gcs_uri: str | None = None,
    ocr_cfg: dict[str, Any],
) -> dict[str, Any]:
    """OCR de imagen con Cloud Vision (document_text_detection)."""
    if not local_path and not gcs_uri:
        raise ValueError("Se requiere local_path o gcs_uri para Vision OCR")

    client = _vision_client()
    image = _vision_image_from_gcs(gcs_uri) if gcs_uri else _vision_image_from_path(local_path)

    image_context = None
    languages = ocr_cfg.get("languages") or []
    if languages:
        from google.cloud import vision

        image_context = vision.ImageContext(language_hints=list(languages))

    response = client.document_text_detection(image=image, image_context=image_context)
    if response.error.message:
        raise RuntimeError(response.error.message)

    annotation = response.full_text_annotation
    text = (annotation.text if annotation else "").strip()
    confidence = _avg_confidence(annotation) if annotation else None

    return {
        "ocr_engine": "vision_api",
        "ocr_method": "vision_document_text_detection",
        "ocr_text": text,
        "ocr_confidence": confidence,
        "page_count": len(annotation.pages) if annotation and annotation.pages else 1,
        "char_count": len(text),
    }


def extract_text_pdf(local_path: str, ocr_cfg: dict[str, Any]) -> dict[str, Any]:
    """PDF: capa de texto nativa; si es escaneado, OCR por página con Vision."""
    import fitz

    min_native = int(ocr_cfg.get("pdf_min_native_chars", 30))
    max_pages_ocr = int(ocr_cfg.get("pdf_max_pages_ocr", 20))
    render_dpi = int(ocr_cfg.get("pdf_render_dpi", 150))

    doc = fitz.open(local_path)
    page_count = len(doc)
    native_parts: list[str] = []

    for page in doc:
        native_parts.append(page.get_text("text").strip())

    native_text = "\n\n".join(p for p in native_parts if p)
    if len(native_text) >= min_native:
        doc.close()
        return {
            "ocr_engine": "pymupdf",
            "ocr_method": "pdf_native_text",
            "ocr_text": native_text,
            "ocr_confidence": None,
            "page_count": page_count,
            "char_count": len(native_text),
        }

    ocr_parts: list[str] = []
    confidences: list[float] = []
    pages_to_scan = min(page_count, max_pages_ocr)

    for page_idx in range(pages_to_scan):
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=render_dpi)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
            pix.save(tmp_path)
        try:
            page_result = extract_text_vision(local_path=tmp_path, gcs_uri=None, ocr_cfg=ocr_cfg)
            page_text = (page_result.get("ocr_text") or "").strip()
            if page_text:
                ocr_parts.append(page_text)
            if page_result.get("ocr_confidence") is not None:
                confidences.append(float(page_result["ocr_confidence"]))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    doc.close()
    combined = "\n\n".join(ocr_parts).strip()
    avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else None

    return {
        "ocr_engine": "vision_api",
        "ocr_method": "vision_pdf_scanned_pages",
        "ocr_text": combined,
        "ocr_confidence": avg_conf,
        "page_count": page_count,
        "char_count": len(combined),
    }


def extract_text(
    *,
    file_name: str,
    mime: str | None,
    ocr_cfg: dict[str, Any],
    local_path: str | None = None,
    source_gcs_uri: str | None = None,
    optimized_gcs_uri: str | None = None,
) -> dict[str, Any]:
    """
    Extrae texto según tipo de archivo.
    Imágenes: Vision (prefiere WebP optimizado en GCS si está configurado).
    PDF: requiere local_path.
    """
    preference = ocr_cfg.get("input_preference", "optimized_webp_then_raw")

    if is_pdf(file_name, mime):
        if not local_path or not os.path.isfile(local_path):
            raise ValueError("PDF requiere archivo local para extracción")
        return extract_text_pdf(local_path, ocr_cfg)

    gcs_input = None
    if preference == "optimized_webp_then_raw" and optimized_gcs_uri:
        gcs_input = optimized_gcs_uri
    elif source_gcs_uri:
        gcs_input = source_gcs_uri

    if gcs_input:
        try:
            return extract_text_vision(gcs_uri=gcs_input, ocr_cfg=ocr_cfg)
        except Exception as gcs_exc:
            logger.warning("Vision OCR desde GCS falló (%s), probando archivo local", gcs_exc)

    if local_path and os.path.isfile(local_path):
        return extract_text_vision(local_path=local_path, ocr_cfg=ocr_cfg)

    raise ValueError("No hay fuente válida para OCR (GCS o archivo local)")
