# Data model

## 1. Storage layout (normative intent)

Under `~/Library/Application Support/MemoryAgent/` (or user override per NFR-3):

| Path | Purpose |
| :--- | :--- |
| `config.json` | Ports, bind address, model names, watched roots, feature flags |
| `secrets/` | Local API token material; never logged |
| `store/vector/` | Vector database files |
| `store/chunks/` | Optional chunk cache or derived text for debugging |
| `mirror/` | Human-readable Markdown mirror (`SOUL.md`, `USER.md`, optional per-topic files) |
| `logs/` | Rotated local logs (no remote shipping) |

`config.json` may optionally include **`ui.chat_welcome_dismissed`** and **`ui.chat_welcome_version`** to mirror first-run chat onboarding state (see [`onboarding.md`](onboarding.md)); the web app may use **`localStorage`** only until the core service persists these fields.

## 2. Core entities

### 2.1 Document

Represents a source item before or after chunking.

| Field | Type | Notes |
| :--- | :--- | :--- |
| `id` | UUID | Stable identifier |
| `source_kind` | enum | `file`, `calendar`, `reminder`, `note`, `user_entry`, `cli` |
| `uri` | string | e.g. `file:///...`, `cal://event/id`, or synthetic |
| `title` | string | Optional display title |
| `content_hash` | string | Hash of canonical extracted text for change detection |
| `updated_at` | ISO-8601 | Last observed modification |
| `acl_tags` | string[] | Optional: `private`, `work` for future filtering |

### 2.2 Chunk

| Field | Type | Notes |
| :--- | :--- | :--- |
| `id` | UUID | |
| `document_id` | UUID | |
| `text` | string | Chunk content |
| `ordinal` | int | Order within document |
| `token_estimate` | int | Optional, for budgeting |
| `metadata` | object | See §3 |

### 2.3 Embedding row

| Field | Type | Notes |
| :--- | :--- | :--- |
| `chunk_id` | UUID | Foreign key |
| `model_id` | string | e.g. `nomic-embed-text-v1.5` |
| `vector` | float[] | Dimension fixed per model |
| `created_at` | ISO-8601 | |

## 3. Chunk metadata (for filtering and audit)

Recommended keys (extensible):

- `source_path` — for file-backed docs  
- `heading` — nearest Markdown heading if detected  
- `mtime` — file modification time  
- `ingestion_job_id` — trace batch  

## 4. Markdown mirror (`SOUL.md` / `USER.md`)

- **Purpose:** Human audit, manual edits, portability ([`requirement.md`](../../requirement.md) UI-3).
- **Rules to finalize in implementation:**
  - Whether these files are **canonical** or **derived** from the vector store.
  - Conflict resolution: if the user edits Markdown while ingestion runs, last-writer-wins vs explicit “sync” action.

**Suggested convention:** YAML front matter for machine fields + Markdown body for narrative memory.

```markdown
---
id: "550e8400-e29b-41d4-a716-446655440000"
updated_at: "2026-04-17T12:00:00Z"
tags: [preferences, work]
---

User prefers concise answers and uses Obsidian for notes.
```

## 5. Deletion and “forget”

- Deleting a **document** must remove all **chunks** and **embeddings** for that document.
- If a file disappears from disk, policy: soft-delete with tombstone vs immediate purge (choose one and document).

## 6. Chunking (design parameters)

Decisions to lock in code and tests:

| Parameter | Starting point | Notes |
| :--- | :--- | :--- |
| Max chunk tokens | 400–800 | Tune per embedding model |
| Overlap | 10–15% | Reduces boundary loss |
| Split strategy | Markdown-aware | Split on headings and code fences when possible |

## 7. Retrieval record (optional, for debugging)

Store last-N retrieval diagnostics per session (local only): query, candidate ids, scores, latency ms. Helps tune rank-based retrieval without cloud telemetry.
