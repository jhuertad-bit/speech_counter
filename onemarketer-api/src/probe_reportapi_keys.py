#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Probe: dump keys crudas de reportapi?type=cases (sin filtrar schema).

Uso (Cloud Shell / local con secretos OM):
  python probe_reportapi_keys.py --day 2026-06-29
  python probe_reportapi_keys.py --day 2026-06-28 --sample 2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any, Dict, List

import requests

from auth_onemarketer import fetch_access_key
from main import normalize_reporte_atenciones_lcra


def _collect_keys(obj: Any, prefix: str = "") -> List[str]:
    keys: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            keys.append(path)
            keys.extend(_collect_keys(v, path))
    elif isinstance(obj, list) and obj:
        keys.extend(_collect_keys(obj[0], f"{prefix}[]"))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe keys reportapi type=cases")
    parser.add_argument("--day", required=True, help="YYYY-MM-DD")
    parser.add_argument("--sample", type=int, default=1, help="N registros de muestra")
    parser.add_argument(
        "--base-url",
        default="https://utp.onemarketer.cl/utp_pregrado/reportapi",
    )
    parser.add_argument("--context", type=int, default=1)
    args = parser.parse_args()

    access_key = fetch_access_key(timeout=30)
    url = f"{args.base_url}?type=cases&day={args.day}&id_context={args.context}&gmt=GMT-03"
    print(f"GET/POST {url}")
    resp = requests.post(url, headers={"X-Signature": access_key}, timeout=60)
    resp.raise_for_status()
    payload = resp.json()

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload["data"]
    elif isinstance(payload, list):
        rows = payload
    else:
        print("Respuesta sin lista data:", type(payload), list(payload)[:20] if isinstance(payload, dict) else "")
        return 1

    print(f"Registros: {len(rows)}")
    if not rows:
        return 0

    key_counter: Counter[str] = Counter()
    for row in rows[: min(50, len(rows))]:
        key_counter.update(_collect_keys(row))

    print("\n=== Top keys (hasta 50 filas) ===")
    for key, count in key_counter.most_common(80):
        print(f"  {count:4d}  {key}")

    lcra_hits = [k for k in key_counter if "lcra" in k.lower() or "listaCasos" in k or "lead" in k.lower() or "dni" in k.lower()]
    print("\n=== Keys relacionadas a lead/dni/lcra/listaCasos ===")
    for key in sorted(lcra_hits):
        print(f"  {key} ({key_counter[key]})")

    print("\n=== Muestra raw + normalizada ===")
    for i, row in enumerate(rows[: args.sample]):
        print(f"\n--- raw[{i}] keys ---")
        print(json.dumps(sorted(row.keys()), ensure_ascii=False, indent=2))
        norm = normalize_reporte_atenciones_lcra(row)
        lcra_vals = {k: norm.get(k) for k in sorted(norm) if k.startswith("lcra_")}
        print(f"--- lcra_* tras normalize[{i}] ---")
        print(json.dumps(lcra_vals, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
