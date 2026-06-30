"""OCR de imágenes/PDFs WhatsApp/OneMarketer → reporte_whatsapp_ocr."""

from __future__ import annotations

import os
from typing import Any

from ocr_engine import extract_text, is_ocr_candidate


def convert_whatsapp_ocr_row(
    *,
    local_source_path: str | None,
    storage_file_name: str,
    source_file_name: str,
    source_gcs_uri: str | None,
    optimized_gcs_uri: str | None,
    gcp_config: dict[str, Any],
    ocr_cfg: dict[str, Any],
    fecha_evento: str,
    chat_line: dict[str, Any],
    mime: str | None,
    media_type: str | None,
    now: str,
) -> dict[str, Any]:
    """Ejecuta OCR y devuelve fila para reporte_whatsapp_ocr."""
    engine_cfg = ocr_cfg.get("ocr", {})
    engine_name = ocr_cfg.get("engine", "vision_api")

    base_row: dict[str, Any] = {
        "fecha_evento": fecha_evento,
        "fecha_procesamiento": now,
        "idcase": chat_line.get("idcase"),
        "idmessage": chat_line.get("idmessage"),
        "waid": chat_line.get("waid"),
        "mime": mime,
        "media_type": media_type,
        "source_gcs_uri": source_gcs_uri,
        "optimized_gcs_uri": optimized_gcs_uri,
        "source_file_name": source_file_name,
        "ocr_engine": engine_name,
        "ocr_method": None,
        "ocr_text": None,
        "ocr_confidence": None,
        "page_count": None,
        "char_count": None,
        "ocr_status": None,
        "error_message": None,
    }

    if not is_ocr_candidate(mime, storage_file_name, media_type):
        base_row["ocr_status"] = "SKIPPED_NOT_APPLICABLE"
        return base_row

    min_chars = int(engine_cfg.get("min_result_chars", 1))

    try:
        result = extract_text(
            file_name=storage_file_name,
            mime=mime,
            ocr_cfg=engine_cfg,
            local_path=local_source_path,
            source_gcs_uri=source_gcs_uri,
            optimized_gcs_uri=optimized_gcs_uri,
        )
        text = (result.get("ocr_text") or "").strip()
        base_row.update(
            {
                "ocr_engine": result.get("ocr_engine") or engine_name,
                "ocr_method": result.get("ocr_method"),
                "ocr_text": text[:1_000_000] if text else None,
                "ocr_confidence": result.get("ocr_confidence"),
                "page_count": result.get("page_count"),
                "char_count": result.get("char_count"),
            }
        )
        if len(text) >= min_chars:
            base_row["ocr_status"] = "OK"
            print(
                f"    [ocr] OK {result.get('ocr_method')} "
                f"chars={result.get('char_count')} conf={result.get('ocr_confidence')}"
            )
        else:
            base_row["ocr_status"] = "SKIPPED_NO_TEXT"
            base_row["error_message"] = "Sin texto detectado"
            print("    [ocr] sin texto detectado")
    except Exception as exc:
        base_row["ocr_status"] = "FAILED"
        base_row["error_message"] = str(exc)[:500]
        print(f"    [ocr] ✗ falló: {exc}")

    return base_row
