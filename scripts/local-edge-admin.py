#!/usr/bin/env python3
"""Inspect or reset the local MP1 Edge Node."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bearer_from_data_dir(data_dir: Path) -> str | None:
    p = data_dir / "secrets" / "bearer.token"
    if not p.is_file():
        return None
    tok = p.read_text(encoding="utf-8").strip()
    return tok or None


def _json_request(
    method: str,
    url: str,
    *,
    token: str | None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as r:
            raw = r.read().decode("utf-8")
            return int(r.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return int(e.code), payload


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "command",
        choices=("health", "status", "reset"),
        help="Edge admin action.",
    )
    ap.add_argument(
        "--edge-base-url",
        default=os.environ.get("EDGE_BASE_URL", "http://127.0.0.1:9876"),
        help="Local Edge Node base URL (default: %(default)s)",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("TOKEN"),
        help="Bearer token. Defaults to MEMORYAGENT_DATA_DIR/secrets/bearer.token.",
    )
    ap.add_argument(
        "--data-dir",
        default=os.environ.get("MEMORYAGENT_DATA_DIR", str(_repo_root() / ".memoryagent")),
        help="Host data dir used to load bearer token (default: repo .memoryagent).",
    )
    args = ap.parse_args()

    token = args.token or _bearer_from_data_dir(Path(args.data_dir))
    if not token:
        print(
            "Bearer token not provided and not found in data dir. "
            "Start the host once or pass --token.",
            file=sys.stderr,
        )
        return 1

    edge = str(args.edge_base_url).rstrip("/")
    if args.command == "health":
        status, payload = _json_request("GET", f"{edge}/health", token=token)
    elif args.command == "status":
        status, payload = _json_request("GET", f"{edge}/index/status", token=token)
    else:
        status, payload = _json_request("POST", f"{edge}/control/reindex", token=token)

    if status >= 400:
        print(f"HTTP {status}", file=sys.stderr)
        _print_json(payload)
        return 1
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
