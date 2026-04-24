#!/usr/bin/env python3
"""Smoke-test a running MemoryAgent host against a real Edge Node (MP1)."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _json_request(
    method: str,
    url: str,
    *,
    token: str | None,
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
    context: ssl.SSLContext | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
            raw = r.read().decode("utf-8")
            return int(r.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return int(e.code), payload


def _bearer_from_data_dir(data_dir: Path) -> str | None:
    p = data_dir / "secrets" / "bearer.token"
    if not p.is_file():
        return None
    tok = p.read_text(encoding="utf-8").strip()
    return tok or None


def _die(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def _assert_status(label: str, status: int, allowed: set[int], payload: dict[str, Any]) -> None:
    if status not in allowed:
        _die(f"{label}: HTTP {status}: {json.dumps(payload, sort_keys=True)[:500]}")


def _retry_retrieve(
    edge_base_url: str,
    edge_token: str,
    query: str,
    *,
    attempts: int,
    delay_seconds: float,
    context: ssl.SSLContext | None,
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for i in range(attempts):
        status, payload = _json_request(
            "POST",
            f"{edge_base_url}/retrieve",
            token=edge_token,
            body={"query": query, "limit": 5},
            context=context,
        )
        _assert_status("edge POST /retrieve", status, {200}, payload)
        results = payload.get("results")
        if not isinstance(results, list):
            _die("edge POST /retrieve response missing results array")
        if results:
            return payload
        last = payload
        if i + 1 < attempts:
            time.sleep(delay_seconds)
    return last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--host-base-url",
        default=os.environ.get("HOST_BASE_URL", "http://127.0.0.1:8765/api/v1"),
        help="MemoryAgent Client API base URL (default: %(default)s)",
    )
    ap.add_argument(
        "--edge-base-url",
        default=os.environ.get("EDGE_BASE_URL"),
        required=os.environ.get("EDGE_BASE_URL") is None,
        help="Edge Node base URL, e.g. https://edge.local:9443",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("TOKEN"),
        help="Bearer token for host and Node API. Defaults to MEMORYAGENT_DATA_DIR/secrets/bearer.token.",
    )
    ap.add_argument(
        "--edge-token",
        default=os.environ.get("EDGE_TOKEN"),
        help="Bearer token for direct Edge Node checks. Defaults to --token.",
    )
    ap.add_argument(
        "--data-dir",
        default=os.environ.get(
            "MEMORYAGENT_DATA_DIR",
            str(Path(__file__).resolve().parents[1] / ".memoryagent"),
        ),
        help="MemoryAgent data dir used to find bearer token (default: repo .memoryagent)",
    )
    ap.add_argument(
        "--require-retrieve-hits",
        action="store_true",
        default=os.environ.get("MP1_REQUIRE_RETRIEVE_HITS") == "1",
        help="Require edge retrieve and host memory search to return at least one hit.",
    )
    ap.add_argument(
        "--retrieve-attempts",
        type=int,
        default=int(os.environ.get("MP1_RETRIEVE_ATTEMPTS", "5")),
        help="Retrieve polling attempts after ingest (default: %(default)s)",
    )
    ap.add_argument(
        "--retrieve-delay-seconds",
        type=float,
        default=float(os.environ.get("MP1_RETRIEVE_DELAY_SECONDS", "1.0")),
        help="Delay between retrieve polling attempts (default: %(default)s)",
    )
    ap.add_argument(
        "--no-restore",
        action="store_true",
        help="Do not restore previous host config at the end.",
    )
    ap.add_argument(
        "--edge-ca-bundle",
        default=os.environ.get("EDGE_CA_BUNDLE"),
        help="PEM CA bundle for direct Edge Node HTTPS checks.",
    )
    ap.add_argument(
        "--edge-insecure-skip-verify",
        action="store_true",
        default=os.environ.get("EDGE_INSECURE_SKIP_VERIFY") == "1",
        help="Disable TLS verification for direct Edge Node checks (lab only).",
    )
    args = ap.parse_args()

    host = args.host_base_url.rstrip("/")
    edge = args.edge_base_url.rstrip("/")
    token = args.token or _bearer_from_data_dir(Path(args.data_dir))
    if not token:
        _die("Bearer token not provided and not found in data dir")
    edge_token = args.edge_token or token
    edge_context = None
    if args.edge_base_url.startswith("https://"):
        if args.edge_insecure_skip_verify:
            edge_context = ssl._create_unverified_context()
        elif args.edge_ca_bundle:
            edge_context = ssl.create_default_context(cafile=args.edge_ca_bundle)

    unique = f"mp1-real-edge-smoke-{int(time.time())}"
    previous_config: dict[str, Any] | None = None

    try:
        status, payload = _json_request(
            "GET", f"{edge}/health", token=edge_token, context=edge_context
        )
        _assert_status("edge GET /health", status, {200}, payload)
        _ok("edge GET /health")

        status, payload = _json_request(
            "POST",
            f"{edge}/ingest",
            token=edge_token,
            body={
                "kind": "memory",
                "text": f"{unique} direct edge memory",
                "tags": ["mp1-smoke"],
                "source": "mp1-edge-smoke-direct",
            },
            context=edge_context,
        )
        _assert_status("edge POST /ingest memory", status, {200, 202}, payload)
        _ok("edge POST /ingest kind=memory")

        payload = _retry_retrieve(
            edge,
            edge_token,
            unique,
            attempts=max(1, args.retrieve_attempts),
            delay_seconds=max(0.0, args.retrieve_delay_seconds),
            context=edge_context,
        )
        if args.require_retrieve_hits and not payload.get("results"):
            _die("edge POST /retrieve returned no hits after direct ingest")
        _ok("edge POST /retrieve schema")

        status, previous_config = _json_request("GET", f"{host}/config", token=token)
        _assert_status("host GET /config", status, {200}, previous_config)

        status, payload = _json_request(
            "PATCH",
            f"{host}/config",
            token=token,
            body={"deployment_mode": "host_edge", "edge_base_url": edge},
        )
        _assert_status("host PATCH /config", status, {200}, payload)
        _ok("host PATCH /config host_edge")

        status, payload = _json_request("GET", f"{host.rsplit('/api/v1', 1)[0]}/api/v1/health", token=None)
        _assert_status("host GET /health", status, {200}, payload)
        dep = payload.get("deployment") or {}
        if dep.get("edge_reachable") is not True or dep.get("degraded") is not False:
            _die(f"host health edge not reachable/non-degraded: {json.dumps(dep, sort_keys=True)}")
        _ok("host GET /health sees edge reachable")

        status, payload = _json_request(
            "GET",
            f"{host}/memory/search?q={urllib.parse.quote(unique)}&limit=5",
            token=token,
        )
        _assert_status("host GET /memory/search", status, {200}, payload)
        results = payload.get("results")
        if not isinstance(results, list):
            _die("host /memory/search response missing results array")
        if args.require_retrieve_hits and not results:
            _die("host /memory/search returned no hits")
        _ok("host /memory/search")

        status, payload = _json_request(
            "POST",
            f"{host}/memory/entries",
            token=token,
            body={
                "text": f"{unique} host memory entry",
                "tags": ["mp1-smoke"],
                "source": "mp1-edge-smoke-host",
            },
        )
        _assert_status("host POST /memory/entries", status, {201}, payload)
        _ok("host POST /memory/entries")

        status, payload = _json_request(
            "POST",
            f"{host}/chat",
            token=token,
            body={
                "messages": [
                    {
                        "role": "user",
                        "content": f"Remember that {unique} chat memory",
                    }
                ]
            },
            timeout=30.0,
        )
        _assert_status("host POST /chat", status, {200}, payload)
        meta = payload.get("meta") or {}
        if meta.get("degraded") is True:
            _die(f"host chat returned degraded meta: {json.dumps(meta, sort_keys=True)}")
        _ok("host POST /chat remember")

        print("PASS: MP1 real-edge smoke completed")
        return 0
    finally:
        if previous_config is not None and not args.no_restore:
            restore = {
                "deployment_mode": previous_config.get("deployment_mode", "standalone"),
                "edge_base_url": previous_config.get("edge_base_url") or "",
                "edge_tls_ca_bundle": previous_config.get("edge_tls_ca_bundle"),
                "edge_tls_insecure_skip_verify": previous_config.get(
                    "edge_tls_insecure_skip_verify", False
                ),
                "edge_tls_spki_pins_sha256": previous_config.get(
                    "edge_tls_spki_pins_sha256", []
                ),
                "edge_ingest_path_host_prefix": previous_config.get(
                    "edge_ingest_path_host_prefix"
                ),
                "edge_ingest_path_edge_prefix": previous_config.get(
                    "edge_ingest_path_edge_prefix"
                ),
            }
            status, payload = _json_request(
                "PATCH",
                f"{host}/config",
                token=token,
                body=restore,
            )
            if status == 200:
                _ok("host config restored")
            else:
                print(
                    "WARN: failed to restore host config: "
                    f"HTTP {status} {json.dumps(payload, sort_keys=True)[:500]}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    raise SystemExit(main())
