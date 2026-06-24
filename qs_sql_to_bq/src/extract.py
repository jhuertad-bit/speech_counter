"""ETL SQL Server → BigQuery (raw_queuesmart)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from google.cloud import bigquery

from audio_filter import (
    audio_in_window,
    format_date_window,
    resolve_date_window,
    resolve_sync_mode,
)
from bq_loader import ensure_table, existing_record_ids, insert_rows, load_schema, utc_now_iso
from sql_client import fetch_rows, parse_audio_date


@dataclass
class ExtractResult:
    mode: str
    date_window: str | None
    sql_rows: int
    candidates: int
    inserted: int
    skipped_existing: int
    skipped_date: int
    skipped_limit: int
    errors: list[str]


def _map_row(
    row: dict[str, Any],
    column_map: dict[str, str],
    *,
    fecha_extraccion: date,
    processed_at: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "fecha_extraccion": fecha_extraccion.isoformat(),
        "fecha_procesamiento": processed_at,
    }
    for sql_col, bq_col in column_map.items():
        value = row.get(sql_col)
        if bq_col == "transferido" and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = None
        if bq_col == "num_celular" and value is not None:
            value = str(value).strip()
        out[bq_col] = value

    audio = out.get("audio")
    if audio:
        out["audio_fecha"] = parse_audio_date(str(audio))
    return out


def run_extract(config: dict[str, Any]) -> ExtractResult:
    sql_cfg = config["sql"]
    gcp_cfg = config["gcp"]
    sync_cfg = config.get("sync", {})
    batch_cfg = config.get("batch", {})
    bq_cfg = config.get("bigquery", {})
    secrets_cfg = config.get("secrets", {})

    mode = resolve_sync_mode(sync_cfg)
    date_start, date_end = resolve_date_window(sync_cfg, mode)
    date_window = format_date_window(date_start, date_end)
    fecha_extraccion = date_end or date_start or date.today()

    column_map: dict[str, str] = sql_cfg.get("column_map", {})
    sql_columns = list(column_map.keys())
    max_rows = int(batch_cfg.get("max_rows", 10000))
    insert_batch = int(batch_cfg.get("insert_batch_size", 500))
    dedupe = bool(bq_cfg.get("dedupe_by_record_id", True))

    processed_at = utc_now_iso()
    errors: list[str] = []

    print(f"[extract] mode={mode} date_window={date_window or 'ALL'}")

    try:
        raw_rows = fetch_rows(sql_cfg, secrets_cfg, sql_columns)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"sql: {type(exc).__name__}: {exc}")
        return ExtractResult(
            mode=mode,
            date_window=date_window,
            sql_rows=0,
            candidates=0,
            inserted=0,
            skipped_existing=0,
            skipped_date=0,
            skipped_limit=0,
            errors=errors,
        )

    candidates: list[dict[str, Any]] = []
    skipped_date = 0
    audio_col = sql_cfg.get("audio_date_column", "Audio")

    for row in raw_rows:
        audio_val = row.get(audio_col)
        if not audio_in_window(
            str(audio_val) if audio_val is not None else None,
            date_start,
            date_end,
        ):
            skipped_date += 1
            continue
        candidates.append(
            _map_row(
                row,
                column_map,
                fecha_extraccion=fecha_extraccion,
                processed_at=processed_at,
            )
        )

    if len(candidates) > max_rows:
        skipped_limit = len(candidates) - max_rows
        candidates = candidates[:max_rows]
    else:
        skipped_limit = 0

    if not bq_cfg.get("enabled", True) or not candidates:
        return ExtractResult(
            mode=mode,
            date_window=date_window,
            sql_rows=len(raw_rows),
            candidates=len(candidates),
            inserted=0,
            skipped_existing=0,
            skipped_date=skipped_date,
            skipped_limit=skipped_limit,
            errors=errors,
        )

    project_id = gcp_cfg["project_id"]
    dataset_id = bq_cfg.get("dataset_id", gcp_cfg.get("dataset_id", "raw_queuesmart"))
    table_id = bq_cfg.get("table_id", "hist_queuesmart_ticketero_raw")
    location = bq_cfg.get("location", "us-central1")
    partition_field = bq_cfg.get("partition_field", "fecha_extraccion")

    client = bigquery.Client(project=project_id)
    schema = load_schema(table_id)
    table_ref = ensure_table(
        client,
        project_id,
        dataset_id,
        table_id,
        schema,
        partition_field=partition_field,
        location=location,
    )

    pending = candidates
    skipped_existing = 0
    if dedupe:
        record_ids = [str(r.get("record_id") or "") for r in candidates]
        already = existing_record_ids(
            client,
            table_ref,
            record_ids,
            fecha_extraccion=fecha_extraccion.isoformat(),
        )
        pending = [r for r in candidates if str(r.get("record_id") or "") not in already]
        skipped_existing = len(candidates) - len(pending)

    inserted = 0
    if pending:
        try:
            inserted = insert_rows(client, table_ref, pending, batch_size=insert_batch)
            print(f"[bq] inserted={inserted} skipped_existing={skipped_existing}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"bigquery: {type(exc).__name__}: {exc}")

    return ExtractResult(
        mode=mode,
        date_window=date_window,
        sql_rows=len(raw_rows),
        candidates=len(candidates),
        inserted=inserted,
        skipped_existing=skipped_existing,
        skipped_date=skipped_date,
        skipped_limit=skipped_limit,
        errors=errors,
    )
