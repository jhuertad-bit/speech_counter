"""BigQuery para reporte_whatsapp_documento_raw (medios descargachats)."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import bigquery

from chat_ids import enrich_media_row


def load_schema(table_name: str = "reporte_whatsapp_documento_raw") -> list[dict[str, Any]]:
    schema_path = os.path.join(os.path.dirname(__file__), "tablas", f"{table_name}.json")
    with open(schema_path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not any(field["name"] == "fecha_evento" for field in schema):
        raise ValueError("El esquema debe incluir fecha_evento")
    return schema


def schema_fields(schema: list[dict[str, Any]]) -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField(field["name"], field["type"], mode=field["mode"])
        for field in schema
    ]


def ensure_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    schema: list[dict[str, Any]],
    partition_field: str = "fecha_evento",
) -> str:
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    try:
        client.get_table(table_ref)
        return table_ref
    except Exception:
        pass

    dataset_ref = f"{project_id}.{dataset_id}"
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset, timeout=30)

    table = bigquery.Table(table_ref, schema=schema_fields(schema))
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field=partition_field,
    )
    client.create_table(table)
    return table_ref


def delete_partition(
    client: bigquery.Client,
    table_ref: str,
    fecha_evento: str,
    partition_field: str = "fecha_evento",
) -> None:
    partition_date = fecha_evento.replace("-", "")
    partition_id = f"{table_ref}${partition_date}"
    try:
        client.delete_table(partition_id)
        print(f"Partición eliminada: {partition_id}")
    except Exception as exc:
        error_str = str(exc).lower()
        if "not found" in error_str or "404" in error_str:
            print(f"Sin partición previa para {fecha_evento}")
        else:
            query = f"""
                DELETE FROM `{table_ref}`
                WHERE {partition_field} = @fecha_evento
            """
            client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                    ]
                ),
            ).result()


def load_media_keys_ok(
    client: bigquery.Client,
    table_ref: str,
    fecha_evento: str,
) -> dict[tuple[int, int], dict[str, Any]]:
    """Claves (idcase, idmessage) ya descargadas con éxito para esa fecha."""
    query = f"""
        SELECT
            idcase, idmessage, gcs_uri, file_name, source_file_name, mime, waid, media_type
        FROM `{table_ref}`
        WHERE fecha_evento = @fecha_evento AND download_status = 'OK'
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return {}
        raise

    out: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        enriched = enrich_media_row(
            {
                "idcase": row.idcase,
                "idmessage": row.idmessage,
                "gcs_uri": row.gcs_uri,
                "file_name": row.file_name,
                "source_file_name": row.source_file_name,
                "mime": row.mime,
                "waid": row.waid,
                "media_type": row.media_type,
            }
        )
        if enriched.get("idcase") is None or enriched.get("idmessage") is None:
            continue
        key = (int(enriched["idcase"]), int(enriched["idmessage"]))
        out[key] = enriched
    return out


def load_pending_mp3_audios(
    client: bigquery.Client,
    doc_table_ref: str,
    mp3_table_ref: str,
    fecha_evento: str,
) -> list[dict[str, Any]]:
    """Audios OK en documento_raw sin registro MP3 terminado."""
    query = f"""
        SELECT
            d.idcase,
            d.idmessage,
            d.gcs_uri,
            d.file_name,
            d.source_file_name,
            d.mime,
            d.waid,
            d.media_type
        FROM `{doc_table_ref}` d
        WHERE d.fecha_evento = @fecha_evento
          AND d.download_status = 'OK'
          AND d.gcs_uri IS NOT NULL
          AND d.file_name IS NOT NULL
          AND (
            LOWER(IFNULL(d.media_type, '')) = 'audio'
            OR REGEXP_CONTAINS(
              LOWER(IFNULL(d.file_name, '')),
              r'\\.(ogg|opus|m4a|amr|wav|flac|aac|webm|caf|aiff|aif|mp3|mpeg|mpg|mov|avi|mkv|m4v|wmv|flv|ts)$'
            )
            OR REGEXP_CONTAINS(
              LOWER(IFNULL(d.mime, '')),
              r'audio|ogg|opus|ptt|voice|amr|video/mpeg|video/mpg|video/x-mpeg'
            )
          )
          AND NOT EXISTS (
            SELECT 1
            FROM `{mp3_table_ref}` m
            WHERE m.fecha_evento = d.fecha_evento
              AND m.idcase = d.idcase
              AND m.idmessage = d.idmessage
              AND m.conversion_status IN (
                'OK', 'SKIPPED_EXISTS', 'SKIPPED_ALREADY_MP3'
              )
          )
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return []
        raise

    pending: list[dict[str, Any]] = []
    for row in rows:
        enriched = enrich_media_row(
            {
                "idcase": row.idcase,
                "idmessage": row.idmessage,
                "gcs_uri": row.gcs_uri,
                "file_name": row.file_name,
                "source_file_name": row.source_file_name,
                "mime": row.mime,
                "waid": row.waid,
                "media_type": row.media_type,
            }
        )
        if enriched.get("idcase") is None or enriched.get("idmessage") is None:
            continue
        pending.append(enriched)
    return pending


def load_pending_optimized_images(
    client: bigquery.Client,
    doc_table_ref: str,
    fecha_evento: str,
    optimized_subfolder: str = "newimages",
) -> list[dict[str, Any]]:
    """Imágenes en documento_raw aún apuntando a media/ (sin optimizar en newimages)."""
    subfolder = optimized_subfolder.strip("/")
    query = f"""
        SELECT
            d.idcase,
            d.idmessage,
            d.gcs_uri,
            d.file_name,
            d.source_file_name,
            d.mime,
            d.waid,
            d.media_type
        FROM `{doc_table_ref}` d
        WHERE d.fecha_evento = @fecha_evento
          AND d.download_status = 'OK'
          AND d.gcs_uri IS NOT NULL
          AND d.file_name IS NOT NULL
          AND (
            LOWER(IFNULL(d.media_type, '')) = 'image'
            OR STARTS_WITH(LOWER(IFNULL(d.mime, '')), 'image/')
            OR REGEXP_CONTAINS(
              LOWER(IFNULL(d.file_name, '')),
              r'\\.(jpe?g|png|gif|bmp|tiff?|webp|avif)$'
            )
          )
          AND REGEXP_CONTAINS(IFNULL(d.gcs_uri, ''), r'/media/')
          AND NOT REGEXP_CONTAINS(IFNULL(d.gcs_uri, ''), r'/{subfolder}/')
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return []
        raise

    pending: list[dict[str, Any]] = []
    for row in rows:
        if row.idcase is None or row.idmessage is None:
            continue
        pending.append(
            {
                "idcase": row.idcase,
                "idmessage": row.idmessage,
                "gcs_uri": row.gcs_uri,
                "file_name": row.file_name,
                "source_file_name": row.source_file_name,
                "mime": row.mime,
                "waid": row.waid,
                "media_type": row.media_type,
            }
        )
    return pending


def load_ocr_keys_done(
    client: bigquery.Client,
    table_ref: str,
    fecha_evento: str,
) -> set[tuple[int, int]]:
    """Claves con OCR ya registrado (éxito o sin texto)."""
    query = f"""
        SELECT idcase, idmessage
        FROM `{table_ref}`
        WHERE fecha_evento = @fecha_evento
          AND ocr_status IN ('OK', 'SKIPPED_NO_TEXT')
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return set()
        raise

    return {
        (int(row.idcase), int(row.idmessage))
        for row in rows
        if row.idcase is not None and row.idmessage is not None
    }


def load_pending_ocr_documents(
    client: bigquery.Client,
    doc_table_ref: str,
    ocr_table_ref: str,
    fecha_evento: str,
) -> list[dict[str, Any]]:
    """Imágenes/PDFs en documento_raw sin OCR (gcs_uri ya es el archivo canónico)."""
    query = f"""
        SELECT
            d.idcase,
            d.idmessage,
            d.gcs_uri,
            d.file_name,
            d.source_file_name,
            d.mime,
            d.waid,
            d.media_type
        FROM `{doc_table_ref}` d
        WHERE d.fecha_evento = @fecha_evento
          AND d.download_status = 'OK'
          AND d.gcs_uri IS NOT NULL
          AND d.file_name IS NOT NULL
          AND (
            LOWER(IFNULL(d.media_type, '')) IN ('image', 'document')
            OR STARTS_WITH(LOWER(IFNULL(d.mime, '')), 'image/')
            OR LOWER(IFNULL(d.mime, '')) LIKE '%pdf%'
            OR REGEXP_CONTAINS(
              LOWER(IFNULL(d.file_name, '')),
              r'\\.(jpe?g|png|gif|bmp|tiff?|webp|avif|pdf)$'
            )
          )
          AND NOT EXISTS (
            SELECT 1
            FROM `{ocr_table_ref}` o
            WHERE o.fecha_evento = d.fecha_evento
              AND o.idcase = d.idcase
              AND o.idmessage = d.idmessage
              AND o.ocr_status IN ('OK', 'SKIPPED_NO_TEXT')
          )
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return []
        raise

    pending: list[dict[str, Any]] = []
    for row in rows:
        if row.idcase is None or row.idmessage is None:
            continue
        pending.append(
            {
                "idcase": row.idcase,
                "idmessage": row.idmessage,
                "gcs_uri": row.gcs_uri,
                "file_name": row.file_name,
                "source_file_name": row.source_file_name,
                "mime": row.mime,
                "waid": row.waid,
                "media_type": row.media_type,
            }
        )
    return pending


def load_documento_optimized_image_keys(
    client: bigquery.Client,
    doc_table_ref: str,
    fecha_evento: str,
    optimized_subfolder: str = "newimages",
) -> set[tuple[int, int]]:
    """Claves en documento_raw cuya gcs_uri ya apunta a la carpeta optimizada."""
    subfolder = optimized_subfolder.strip("/")
    query = f"""
        SELECT idcase, idmessage
        FROM `{doc_table_ref}`
        WHERE fecha_evento = @fecha_evento
          AND download_status = 'OK'
          AND REGEXP_CONTAINS(IFNULL(gcs_uri, ''), r'/{subfolder}/')
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return set()
        raise

    return {
        (int(row.idcase), int(row.idmessage))
        for row in rows
        if row.idcase is not None and row.idmessage is not None
    }


def load_mp3_keys_done(
    client: bigquery.Client,
    table_ref: str,
    fecha_evento: str,
) -> set[tuple[int, int]]:
    """Claves con MP3 ya registrado (éxito o skip válido)."""
    query = f"""
        SELECT idcase, idmessage
        FROM `{table_ref}`
        WHERE fecha_evento = @fecha_evento
          AND conversion_status IN (
            'OK', 'SKIPPED_EXISTS', 'SKIPPED_ALREADY_MP3'
          )
    """
    try:
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                ]
            ),
        ).result()
    except Exception as exc:
        err = str(exc).lower()
        if "not found" in err or "404" in err:
            return set()
        raise

    return {
        (int(row.idcase), int(row.idmessage))
        for row in rows
        if row.idcase is not None and row.idmessage is not None
    }


def update_documento_raw_storage(
    client: bigquery.Client,
    table_ref: str,
    fecha_evento: str,
    idcase: int,
    idmessage: int,
    gcs_uri: str,
    file_name: str,
    file_size_bytes: int | None = None,
    mime: str | None = None,
) -> None:
    """Actualiza gcs_uri/file_name en documento_raw tras optimizar (sin duplicar fila)."""
    query = f"""
        UPDATE `{table_ref}`
        SET
          gcs_uri = @gcs_uri,
          file_name = @file_name,
          file_size_bytes = COALESCE(@file_size_bytes, file_size_bytes),
          mime = COALESCE(@mime, mime)
        WHERE fecha_evento = @fecha_evento
          AND idcase = @idcase
          AND idmessage = @idmessage
    """
    params = [
        bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
        bigquery.ScalarQueryParameter("idcase", "INT64", idcase),
        bigquery.ScalarQueryParameter("idmessage", "INT64", idmessage),
        bigquery.ScalarQueryParameter("gcs_uri", "STRING", gcs_uri),
        bigquery.ScalarQueryParameter("file_name", "STRING", file_name),
        bigquery.ScalarQueryParameter("file_size_bytes", "INT64", file_size_bytes),
        bigquery.ScalarQueryParameter("mime", "STRING", mime),
    ]
    client.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=params),
    ).result()


def insert_rows(
    client: bigquery.Client,
    dataset_id: str,
    table_id: str,
    rows: list[dict[str, Any]],
    batch_size: int = 500,
) -> None:
    if not rows:
        return
    table_ref = client.dataset(dataset_id).table(table_id)
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            raise RuntimeError(f"Errores insertando en BigQuery: {errors[:3]}")
