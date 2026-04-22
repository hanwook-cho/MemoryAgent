#!/usr/bin/env python3
"""M5 benchmark helper: cold/warm first-token + idle CPU/RSS snapshots.

Usage:
  python scripts/benchmark_m5.py
  python scripts/benchmark_m5.py --base http://127.0.0.1:8765/api/v1 --out docs/benchmarks/m5-latest.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_token(data_dir: Path) -> str:
    p = data_dir / "secrets" / "bearer.token"
    return p.read_text(encoding="utf-8").strip()


def _http_json(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return e.code, parsed


def _measure_chat_latency_ms(base: str, token: str, prompt: str) -> int:
    t0 = time.perf_counter_ns()
    code, _ = _http_json(
        "POST",
        f"{base}/chat",
        token,
        {"messages": [{"role": "user", "content": prompt}]},
    )
    if code != 200:
        raise RuntimeError(f"/chat failed with status {code}")
    t1 = time.perf_counter_ns()
    return int((t1 - t0) / 1_000_000)


def _measure_first_token_ms(base: str, token: str, prompt: str) -> int:
    url = f"{base}/chat/stream"
    body = json.dumps({"messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    t0 = time.perf_counter_ns()
    with urllib.request.urlopen(req, timeout=60) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if line == "event: token":
                t1 = time.perf_counter_ns()
                return int((t1 - t0) / 1_000_000)
    raise RuntimeError("No token event received from /chat/stream")


def _server_pid(port: int) -> int | None:
    try:
        out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s)
    return None


def _idle_snapshots(pid: int, samples: int, interval_s: float) -> list[tuple[float, int]]:
    rows: list[tuple[float, int]] = []
    for _ in range(samples):
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "%cpu=", "-o", "rss="],
            text=True,
        ).strip()
        # output is usually: "<cpu> <rss_kb>"
        parts = out.split()
        if len(parts) >= 2:
            cpu = float(parts[0])
            rss_kb = int(parts[1])
            rows.append((cpu, rss_kb))
        time.sleep(interval_s)
    return rows


def _machine_summary() -> str:
    sw_vers = ""
    try:
        sw_vers = subprocess.check_output(["sw_vers"], text=True).strip().replace("\n", "; ")
    except Exception:
        sw_vers = "sw_vers unavailable"
    return (
        f"{platform.system()} {platform.release()} ({platform.machine()}) | "
        f"{platform.processor() or 'processor-unknown'} | {sw_vers}"
    )


def _render_md(
    *,
    timestamp_utc: str,
    base: str,
    prompt: str,
    machine: str,
    cold_ttft_ms: int,
    warm_ttft_ms: int,
    cold_chat_ms: int,
    warm_chat_ms: int,
    idle_rows: list[tuple[float, int]],
) -> str:
    idle_cpu_avg = sum(r[0] for r in idle_rows) / max(1, len(idle_rows))
    idle_rss_avg_mb = (sum(r[1] for r in idle_rows) / max(1, len(idle_rows))) / 1024.0
    lines = [
        "# M5 NFR Baseline Report",
        "",
        f"- **Timestamp (UTC):** {timestamp_utc}",
        f"- **API base:** `{base}`",
        f"- **Prompt:** `{prompt}`",
        f"- **Machine:** {machine}",
        "",
        "## Latency",
        "",
        "| Metric | Value |",
        "| :--- | ---: |",
        f"| Cold first token (`/chat/stream`) | {cold_ttft_ms} ms |",
        f"| Warm first token (`/chat/stream`) | {warm_ttft_ms} ms |",
        f"| Cold full chat (`/chat`) | {cold_chat_ms} ms |",
        f"| Warm full chat (`/chat`) | {warm_chat_ms} ms |",
        "",
        "## Idle process snapshots",
        "",
        "| Sample | CPU % | RSS (MiB) |",
        "| :--- | ---: | ---: |",
    ]
    for i, (cpu, rss_kb) in enumerate(idle_rows, start=1):
        lines.append(f"| {i} | {cpu:.2f} | {rss_kb / 1024.0:.1f} |")
    lines.extend(
        [
            "",
            f"- **Idle CPU avg:** {idle_cpu_avg:.2f} %",
            f"- **Idle RSS avg:** {idle_rss_avg_mb:.1f} MiB",
            "",
            "## Notes",
            "",
            "- Run this multiple times and compare cold vs warm behavior on the same machine.",
            "- Keep Ollama model, system load, and background apps consistent across runs.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate M5 NFR baseline report")
    parser.add_argument("--base", default="http://127.0.0.1:8765/api/v1")
    parser.add_argument("--data-dir", default=str(Path.cwd() / ".memoryagent"))
    parser.add_argument("--prompt", default="Give me a two-sentence status summary of my memory context.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--idle-samples", type=int, default=5)
    parser.add_argument("--idle-interval", type=float, default=2.0)
    parser.add_argument("--out", default="docs/benchmarks/m5-latest.md")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    data_dir = Path(args.data_dir).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    token = _read_token(data_dir)
    health_url = f"{base}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=10) as resp:
            if resp.getcode() != 200:
                raise RuntimeError(f"/health returned {resp.getcode()}")
    except Exception as e:
        print(f"ERROR: health check failed at {health_url}: {e}", file=sys.stderr)
        return 2

    # ensure auth works
    code, _ = _http_json("GET", f"{base}/config", token)
    if code != 200:
        print(f"ERROR: token/config check failed with status {code}", file=sys.stderr)
        return 2

    pid = _server_pid(args.port)
    if pid is None:
        print(
            f"ERROR: could not find server PID on port {args.port}. Is memoryagent-core running?",
            file=sys.stderr,
        )
        return 2

    cold_ttft_ms = _measure_first_token_ms(base, token, args.prompt)
    warm_ttft_ms = _measure_first_token_ms(base, token, args.prompt)
    cold_chat_ms = _measure_chat_latency_ms(base, token, args.prompt)
    warm_chat_ms = _measure_chat_latency_ms(base, token, args.prompt)
    idle_rows = _idle_snapshots(pid, args.idle_samples, args.idle_interval)

    md = _render_md(
        timestamp_utc=_now_utc(),
        base=base,
        prompt=args.prompt,
        machine=_machine_summary(),
        cold_ttft_ms=cold_ttft_ms,
        warm_ttft_ms=warm_ttft_ms,
        cold_chat_ms=cold_chat_ms,
        warm_chat_ms=warm_chat_ms,
        idle_rows=idle_rows,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote benchmark report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
