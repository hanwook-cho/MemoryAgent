# M5 NFR Baseline Report

- **Timestamp (UTC):** 2026-04-22T17:54:11Z
- **API base:** `http://127.0.0.1:8765/api/v1`
- **Prompt:** `Give me a two-sentence status summary of my memory context.`
- **Machine:** Darwin 25.4.0 (arm64) | arm | ProductName:		macOS; ProductVersion:		26.4.1; BuildVersion:		25E253

## Latency

| Metric | Value |
| :--- | ---: |
| Cold first token (`/chat/stream`) | 4361 ms |
| Warm first token (`/chat/stream`) | 2318 ms |
| Cold full chat (`/chat`) | 1600 ms |
| Warm full chat (`/chat`) | 2160 ms |

## Idle process snapshots

| Sample | CPU % | RSS (MiB) |
| :--- | ---: | ---: |
| 1 | 0.00 | 27.8 |
| 2 | 0.00 | 27.8 |
| 3 | 0.00 | 27.8 |
| 4 | 0.00 | 27.8 |
| 5 | 0.00 | 27.8 |

- **Idle CPU avg:** 0.00 %
- **Idle RSS avg:** 27.8 MiB

## Notes

- Run this multiple times and compare cold vs warm behavior on the same machine.
- Keep Ollama model, system load, and background apps consistent across runs.

## M5 verification

**2026-04-23:** NFR-1/NFR-2 **accepted for the M5 gate** — **NFR-2** (idle CPU) satisfied by the samples above; **NFR-1** (time to first token) **baselined** via this report and [`scripts/benchmark_m5.py`](../../scripts/benchmark_m5.py). Reference hardware is **Apple Silicon** as summarized in the **Machine** line ([`requirement.md`](../../requirement.md) §3.1, [`docs/spec/milestones.md`](../spec/milestones.md) M5).
