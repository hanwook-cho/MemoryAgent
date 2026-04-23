# Prerequisites — software on macOS

This document lists what must be present on a Mac to **run** MemoryAgent as specified in [`requirement.md`](../../requirement.md) (local web UI, on-device LLM, local memory). Version pins belong in the implementation repo once the stack is chosen.

---

## 1. Baseline (end user — running the shipped product)

| Requirement | Notes |
| :--- | :--- |
| **macOS** | Aligned with **Apple Silicon (M1+)** as the performance baseline; Intel Macs may run but are not the reference ([`requirement.md`](../../requirement.md) §6). |
| **Modern web browser** | For the **local web application** (Safari, Chrome, Edge, Firefox, etc.). |
| **On-device LLM runtime (at least one)** | Satisfies **FR-4**: e.g. **Ollama**, **[mlx-lm](https://github.com/ml-explore/mlx-lm)** (MLX on Apple Silicon—often used **in-process** from Python), an MLX-based HTTP wrapper, or a **llama.cpp**-compatible local server. Must run **on the same machine**; cloud APIs are not part of default operation. |
| **Chat model (local)** | Pulled or bundled for the chosen runtime—typically a small instruct model sized to available unified memory (e.g. Llama-class 3B/8B or equivalent). |
| **Embedding model (local)** | Satisfies **FR-5**—e.g. `nomic-embed-text` or another embedding model your stack runs **locally**. |
| **MemoryAgent core service** | The shipped binary or launcher that hosts the loopback API, RAG, and vector store ([`architecture.md`](architecture.md)). |

After models are installed, **no internet** is required for core operation (**FR-8**).

---

## 2. Development (engineers building from source)

| Requirement | Notes |
| :--- | :--- |
| **Git** | Version control. |
| **Core language runtime(s)** | Depends on implementation (e.g. Python 3.11+ for a Python core, Node.js LTS for a JS/TS web toolchain). Not fixed in the SRS; follow the repository `README` when it exists. |
| **Same local LLM + embedding setup as §1** | Needed to exercise chat and indexing end-to-end. |
| **Document extraction dependencies** | For source builds with PDF/DOCX ingest enabled: Python deps include `pypdf` and `python-docx` (installed by `pip install -e ".[dev]"` in current implementation). |

---

## 3. Recommended (not strictly required)

| Item | Notes |
| :--- | :--- |
| **Homebrew** | Simplifies installing Ollama, runtimes, and CLI tools on macOS. |
| **Xcode / command-line tools** | Required only if you build or sign **native Swift** helpers, or compile certain native dependencies. |

---

## 4. Bundled vs user-installed LLM

| Approach | Tradeoff |
| :--- | :--- |
| **User installs Ollama (or similar)** | Smaller app bundle; user runs `ollama pull` (or GUI); app checks reachability (e.g. [`client-api.md`](client-api.md) `/health` `llm` field). |
| **Bundle mlx-lm + MLX weights in-app** | Apple Silicon–optimized path; core service loads models via **mlx-lm** (no separate Ollama daemon). Larger download and update cycles. |

The product must remain usable **offline** after assets are local (**FR-8**).

---

## 5. Explicitly not required for core behavior

- Cloud LLM or embedding APIs (default operation is on-device per **FR-4** and **FR-8**).
- Ongoing internet connectivity after models and the app are installed.

---

## 6. Quick checklist (Ollama-oriented default)

1. Install **Ollama** for macOS (Apple Silicon build).
2. Pull a **chat** model and an **embedding** model your implementation expects.
3. Install or run **MemoryAgent** core service; open the **local web UI** in the browser.
4. Grant **macOS permissions** only when features need them ([`permissions-matrix.md`](permissions-matrix.md)).

Adjust step 1–2 if you standardize on **mlx-lm** (MLX) or **llama.cpp** instead of Ollama.

### Calendar read tool (`calendar.list_events`)

The core uses a **native Swift** helper (`memoryagent-calendar`) for EventKit. macOS shows **Calendar** access under **Privacy & Security → Calendars** per **host app** (the process that runs Python / spawns the helper).

**Practical note:** When you start `./scripts/run.sh` from **Cursor’s integrated terminal**, that app may **not appear** in the Calendars list the same way as **Terminal.app**. If prompts or toggles are missing or the tool returns `PERMISSION_DENIED`, run the server from **standalone Terminal.app** once and approve access there, **or** enable Calendar (and **Full access** if shown) explicitly for **Cursor** and **Python** / your venv interpreter when it appears in the list.

---

## 7. One-shot setup scripts (repository requirement)

Any tool that must be **installed or configured** before developers can run tests or the app (see [`test-plan.md`](test-plan.md)) **must** be covered by a **single command** documented here and in the repository root `README` when it exists.

| Deliverable | Purpose |
| :--- | :--- |
| **`scripts/setup-dev.sh`** | **Idempotent** macOS bootstrap: verify **Homebrew**, install **Ollama** if missing, **`ollama pull`** default chat + embedding models (configurable via env vars). Run from repo root: `./scripts/setup-dev.sh`. |
| **`scripts/run.sh`** | **One-shot run:** ensure `services/core/.venv` + `web/dist` exist (creates/builds if missing), then **`exec`** `memoryagent-core`. Run from repo root: `./scripts/run.sh`. |
| **Future: `scripts/setup-dev-extra.sh`** (optional) | Add **Python venv**, **Node** dependencies, **pre-commit**, or **mlx-lm** setup once the monorepo stack is fixed ([`milestones.md`](milestones.md) M0). |

**Rules**

1. **One-shot:** A new engineer follows **one** primary command (plus documented env vars) without hunting separate install pages for routine deps.
2. **Safe to re-run:** Scripts use `set -euo pipefail` (or equivalent) and skip redundant work where possible.
3. **Honest failures:** If **Ollama** is not running, the script prints exact **follow-up commands** (e.g. `ollama pull …`) instead of failing silently.
4. **End-user packaging** (signed `.app`, `launchd`) may use a **different** installer; `setup-dev.sh` targets **developers** and manual QA machines.

**Environment variables** (defaults match common Ollama model names; adjust when the implementation pins versions):

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `CHAT_MODEL` | `llama3.2` | Pulled chat model tag (matches `AppConfig.chat_model`) |
| `EMBED_MODEL` | `nomic-embed-text` | Pulled embedding model tag |

**Swift / Xcode:** If the native bridge is required for local dev, extend the one-shot story with `xcodebuild -scheme …` or document **Xcode Open Package** in the same README section—do not rely on undocumented manual steps.
