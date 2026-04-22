Since you're building a local-first, on-device memory assistant on macOS—similar to the architecture of **niftyMomnt** but focused on system-wide memory—this **Software Requirements Specification (SRS)** focuses on privacy, local performance, and system integration.

---

## 1. Introduction
### 1.1 Purpose
This document outlines the requirements for a local-first AI Memory Assistant for macOS. The system will observe user activity, manage a persistent long-term memory, and provide an interface for retrieval, all while keeping data strictly on-device.

### 1.2 System Overview
The assistant acts as a "second brain" that bridges the gap between raw OS data (files, calendar, and optional app integrations) and a local Large Language Model (LLM) using the **Model Context Protocol (MCP)** and **RAG (Retrieval-Augmented Generation)**. **Primary user interaction** is a **local web application** (browser UI backed by a loopback-only HTTP API on the same Mac); optional native surfaces may open or complement that UI.

---

## 2. Functional Requirements

### 2.1 Context Capture & Observation
* **FR-1: File System Monitoring:** The system must watch designated directories (e.g., `Documents`, `Desktop`) for new or modified files.
* **FR-2: Application Integration:** The system shall interface with macOS apps (Calendar, Reminders, Notes) via AppleScript or native APIs to **read** upcoming events and tasks and, when the user requests via tools, **create** calendar events (EventKit). **Preferred mechanisms:** **EventKit** (Swift) for Calendar and Reminders; **AppleScript / Automation** for Notes only where necessary, with user consent per [`docs/spec/permissions-matrix.md`](docs/spec/permissions-matrix.md). When creating events such as repeat appointments **without** a stated place, the system should **infer location** from **recent matching calendar history** and **saved memory** before asking the user, per [`docs/spec/agent-actions.md`](docs/spec/agent-actions.md) §3.4.
* **FR-3: Active Memory Entry:** Users must be able to "tell" the assistant facts via a CLI, a lightweight "Quick Entry" UI, **or natural-language chat** that persists through the same ingestion pipeline as manual entry (see [`docs/spec/agent-actions.md`](docs/spec/agent-actions.md)).

#### 2.1.1 OS integration priority (v1)
Implementation should start with **well-supported, documented APIs** and **user-chosen paths**; request macOS capabilities only when a feature needs them (NFR-4).

| Priority | Source | Approach | Notes |
| :--- | :--- | :--- | :--- |
| **1 — First** | Manual entry, paste, CLI, quick entry | No extra TCC beyond app sandbox defaults | Validates RAG and UX before OS hooks ([`docs/spec/milestones.md`](docs/spec/milestones.md) M1). |
| **2 — Early** | User-selected folders | Files and Folders (per-directory) or security-scoped bookmarks; avoid Full Disk Access until required | Aligns with FR-1 ([`docs/spec/milestones.md`](docs/spec/milestones.md) M2). |
| **3 — Next** | Calendar, Reminders | **EventKit** via a small native bridge; standard Calendars / Reminders prompts | Primary structured OS integration ([`docs/spec/milestones.md`](docs/spec/milestones.md) M4). |
| **4 — Optional** | Notes | Automation (Apple Events) for Notes, or export-based ingestion | More brittle than EventKit; feature-gated. |
| **Defer** | Mail | Prefer **IMAP (or provider APIs)** with user-configured accounts if email ingestion is added later | Scraping Mail.app is not a v1 goal. |
| **Out of scope (v1)** | iMessage, Apple Journal | No stable public APIs for full history; **do not** rely on private database paths as a product baseline | Revisit only if Apple ships APIs or explicit user export flows exist. |

### 2.2 Local Intelligence (The Brain)
* **FR-4: On-Device Inference:** All **chat completion** for core features must run **on the same Mac** via a **local inference runtime** optimized for Apple Silicon (e.g., **Ollama**, **MLX** via **mlx-lm**, or **llama.cpp**-compatible servers). **Remote or API-based cloud LLMs are out of scope** for default operation and must not be required for the product to function (see FR-8). Optional pluggable backends may be considered later but do not change the on-device default.
* **FR-5: Local Embeddings:** All text chunks must be converted into vector embeddings locally using a model like `nomic-embed-text`.
* **FR-6: Tool Execution:** The agent must be able to execute local scripts (Python/Swift) to perform actions like "Find a file" or "Create a calendar invite."

### 2.3 Memory Management
* **FR-7: Persistent Storage:** Memories must be stored in a local vector database (e.g., **ChromaDB**) and a human-readable fallback (Markdown files).
* **FR-8: Privacy Firewall:** The system must function entirely without an internet connection. No data shall be transmitted to external servers.

---

## 3. Non-Functional Requirements

### 3.1 Performance
* **NFR-1: Response Latency:** Local inference should begin generating a response within **2.0 seconds** on M-series Silicon.
* **NFR-2: Resource Caps:** The background observation service must not exceed **5% CPU** usage during idle monitoring.

### 3.2 Security & Privacy
* **NFR-3: Zero-Cloud Policy:** All data, including vector weights and chat history, must reside in the user's `~/Library/Application Support/` or a user-defined local path.
* **NFR-4: Permission Scoping:** The app must request specific macOS permissions (Full Disk Access, Accessibility, Calendars) only when required for a specific "Claw" (tool).

---

## 4. System Architecture (High-Level)

| Component | Technology Stack |
| :--- | :--- |
| **Inference Engine** | On-device only: **Ollama**, **MLX** (**mlx-lm** in-process or a small local server), or equivalent Mac-optimized local runtime (typical chat models: small instruct models such as Llama 3.2 3B/8B class, sized to the machine) |
| **Vector DB** | LanceDB or ChromaDB (Local mode) |
| **Orchestration** | LangGraph or CrewAI |
| **Client UI** | Web app (SPA) + local HTTP API (loopback) |
| **OS Interface** | Core logic (e.g. Python) + optional Swift helper for deep system integration |
| **Protocol** | Model Context Protocol (MCP) |

---

## 5. User Interface Requirements
* **UI-1: Local Web Application:** The main experience is a browser-based app served from the local core service (default bind `127.0.0.1`), providing chat, memory search, settings, and status. The API must not rely on external hosting for core features.
* **UI-2: Menu Bar App (optional):** A persistent icon in the macOS Menu Bar for quick status checks, opening the web UI in the default browser, and manual triggers.
* **UI-3: Floating Command Bar (optional):** A Spotlight-like native overlay (similar to Raycast) for asking questions; may defer to opening the web UI in early milestones.
* **UI-4: Markdown View:** A way for the user to manually audit and edit their `SOUL.md` and `USER.md` (or equivalent) files—implemented in the web app or linked external editor, consistent with the human-readable store (FR-7).
* **UI-5: First-Run Chat Welcome:** The first time the user opens Chat with an empty thread, the web app shall display a **static** assistant introduction and brief “how to use” guidance (no LLM call for that content), then remember that the user has seen it per [`docs/spec/onboarding.md`](docs/spec/onboarding.md). Settings may offer **Show welcome again**.

---

## 6. Constraints & Risks
* **Hardware Dependency:** The system is optimized for Apple Silicon (M1+) and may perform poorly on Intel-based Macs.
* **Context Window Limits:** On-device models have limited context; the system must implement efficient **Rank-based Retrieval** to ensure the LLM receives only the most relevant memory snippets.

---

Detailed technical specifications live under **`docs/spec/`** (architecture, data model, local HTTP API for the web app, **conversational actions** memory/calendar, **first-run chat onboarding**, permissions matrix, milestones, **test plan**, **macOS prerequisites including local LLM**). Developer one-shot setup is required per **`docs/spec/prerequisites.md`** §7 (`scripts/setup-dev.sh`).