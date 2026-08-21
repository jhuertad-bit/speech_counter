"""Copia GCS→GCS entre proyectos."""

from __future__ import annotations

from typing import Any

from google.cloud import storage

from secrets_loader import credentials_from_info, load_source_sa_info


def storage_client(project_id: str, credentials: Any | None = None) -> storage.Client:
    if credentials is not None:
        return storage.Client(project=project_id, credentials=credentials)
    return storage.Client(project=project_id)


def source_storage_client(config: dict[str, Any]) -> storage.Client:
    """Cliente origen: JSON de SA (Secret Manager / archivo) o ADC del Job."""
    src_cfg = config["source"]
    secrets_cfg = config.get("secrets", {})
    info = load_source_sa_info(secrets_cfg)
    project_id = str(src_cfg.get("project_id") or "").strip()
    if info:
        json_project = str(info.get("project_id") or "").strip()
        if not project_id or project_id == "REPLACE_SOURCE_PROJECT":
            project_id = json_project
        email = info.get("client_email", "")
        print(f"[promotores_gcs_copy] origen con SA JSON client_email={email} project={project_id}")
        return storage_client(project_id, credentials=credentials_from_info(info))
    print(f"[promotores_gcs_copy] origen con ADC del Job project={project_id}")
    return storage_client(project_id)


def source_uses_sa_json(config: dict[str, Any]) -> bool:
    return load_source_sa_info(config.get("secrets", {})) is not None


def list_source_objects(
    src_client: storage.Client,
    bucket: str,
    prefix: str,
    min_size: int,
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for blob in src_client.list_blobs(bucket, prefix=prefix or ""):
        name = blob.name
        if not name or name.endswith("/"):
            continue
        size = int(blob.size or 0)
        if size < min_size:
            continue
        objects.append(
            {
                "key": name,
                "size": size,
                "file_name": name.rsplit("/", 1)[-1],
                "content_type": blob.content_type,
            }
        )
    objects.sort(key=lambda x: x["key"])
    return objects


def dest_exists(dst_client: storage.Client, bucket: str, object_name: str) -> bool:
    return dst_client.bucket(bucket).blob(object_name).exists()


def rewrite_object(
    src_client: storage.Client,
    dst_client: storage.Client,
    *,
    src_bucket: str,
    src_key: str,
    dst_bucket: str,
    dst_key: str,
) -> int:
    src_blob = src_client.bucket(src_bucket).blob(src_key)
    dst_blob = dst_client.bucket(dst_bucket).blob(dst_key)
    token: str | None = None
    rewritten = 0
    while True:
        token, rewritten, _total = dst_blob.rewrite(src_blob, token=token)
        if not token:
            break
    dst_blob.reload()
    return int(dst_blob.size or rewritten or 0)


def stream_copy_object(
    src_client: storage.Client,
    dst_client: storage.Client,
    *,
    src_bucket: str,
    src_key: str,
    dst_bucket: str,
    dst_key: str,
) -> int:
    """Lee con credenciales origen y escribe con las del Job (dos identidades)."""
    src_blob = src_client.bucket(src_bucket).blob(src_key)
    src_blob.reload()
    dst_blob = dst_client.bucket(dst_bucket).blob(dst_key)
    with src_blob.open("rb") as reader:
        dst_blob.upload_from_file(
            reader,
            size=src_blob.size,
            content_type=src_blob.content_type,
        )
    dst_blob.reload()
    return int(dst_blob.size or src_blob.size or 0)


def copy_object(
    src_client: storage.Client,
    dst_client: storage.Client,
    *,
    src_bucket: str,
    src_key: str,
    dst_bucket: str,
    dst_key: str,
    use_stream: bool,
) -> int:
    if use_stream:
        return stream_copy_object(
            src_client,
            dst_client,
            src_bucket=src_bucket,
            src_key=src_key,
            dst_bucket=dst_bucket,
            dst_key=dst_key,
        )
    return rewrite_object(
        src_client,
        dst_client,
        src_bucket=src_bucket,
        src_key=src_key,
        dst_bucket=dst_bucket,
        dst_key=dst_key,
    )
