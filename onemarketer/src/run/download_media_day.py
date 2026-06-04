#!/usr/bin/env python3
"""Ejecución local: descarga medios descargachats para un día."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from download_chat_media import process_media_for_date
from extract_chats import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "config.json"),
    )
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    media_cfg = config.setdefault("descargaChatsMedia", {})
    media_cfg.setdefault("enabled", True)
    media_cfg.setdefault("api", {})["fechaini"] = args.fecha
    if args.local_only:
        media_cfg.setdefault("storage", {})["upload_gcs"] = False
        media_cfg["storage"]["save_local_files"] = True

    chat_messages = None
    jsonl = os.path.join(os.path.dirname(__file__), "..", "reporteChats.jsonl")
    if os.path.isfile(jsonl):
        chat_messages = []
        with open(jsonl, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    chat_messages.append(json.loads(line))

    result = process_media_for_date(args.fecha, config, chat_messages=chat_messages)
    print(result)
    if result.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
