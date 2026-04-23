# Conversational actions (memory save & calendar create)

This document specifies **user-initiated capabilities** exposed through **chat**: saving something to long-term memory when the user asks, and **creating** a Calendar event when the user asks. Implementation uses **tool calling** (or an equivalent planner step) in the orchestrator, backed by the **same HTTP/native behaviors** as manual UI actions.

## 1. Goals

| Capability | User intent (examples) | Backend | macOS permission |
| :--- | :--- | :--- | :--- |
| **Remember / memorize** | “Remember that my bike lock code is 0421”, “Note this: …” | Ingest like [`client-api.md`](client-api.md) `POST /memory/entries` → chunk + embed + vector upsert | None beyond app storage (NFR-3) |
| **Create calendar event** | “Put a meeting on my calendar Tuesday 3pm”, “Remind me on the calendar …” (interpreted as **event**, not Reminders) | **EventKit** create in native bridge; optional HTTP wrapper below | **Calendars** (see [`permissions-matrix.md`](permissions-matrix.md)) |
| **Place / address reuse** | “Dentist appointment July 1 at 2pm” (no address given) | **Read** past events + **memory search** to fill `location`; see §3.4 | Same **Calendars** read as query; **none** extra for memory |

**Out of scope for this doc (unless specified later):** deleting or editing Calendar events, creating **Reminders** app tasks (different EventKit entity), sending email, or writing to third-party apps.

## 2. Memory save from chat

### 2.1 Behavior

- When the user’s message clearly requests **storing** a fact (not only asking a question), the orchestrator should invoke a tool such as **`memory.save`** (name is implementation-defined) with structured fields.
- **Payload (conceptual):**

| Field | Required | Notes |
| :--- | :--- | :--- |
| `text` | yes | Canonical text to remember (normalized: strip “remember that” wrappers when safe). |
| `tags` | no | Short labels, e.g. `["personal"]`. |
| `source` | yes | Constant e.g. `chat` for provenance. |

- **Pipeline:** Identical to manual entry (FR-7): persist document, chunk, embed, upsert vector store; update Markdown mirror per policy.
- **Reply:** The assistant confirms in natural language, e.g. “Saved. I’ll be able to find this when you ask about …” Optionally include `document_id` in tool result for UI “jump to source.”

### 2.2 Safety and UX

- **Ambiguity:** If the model is unsure whether the user wanted to save vs. only chat, **prefer asking one short clarifying question** instead of saving.
- **Sensitive content:** Do not block automatically; user owns the machine. Optional **Settings** flag “Always confirm before saving from chat” can force a confirmation chip before ingest.
- **No silent overwrite:** Saves are **append-only** new memory documents unless a future spec adds explicit “replace memory X.”

## 3. Create Calendar event from chat

### 3.1 Behavior

- When the user asks to **schedule** or **add to calendar**, invoke **`calendar.create_event`** (or equivalent) with structured time and title.
- **Payload (conceptual):**

| Field | Required | Notes |
| :--- | :--- | :--- |
| `title` | yes | Event title. |
| `starts_at` | yes | ISO-8601 with offset or Z; orchestrator must resolve **relative** language (“next Tuesday 3pm”) using the **user’s local timezone** from `config` or system default. |
| `ends_at` | no | Default: `starts_at + 1 hour` if omitted for timed events. |
| `all_day` | no | Default `false`. |
| `notes` | no | Body/description in Calendar. |
| `location` | no | Physical address or place name for Maps / Calendar location field; may be **filled automatically** per §3.4. |
| `calendar_id` | no | Target calendar; default = system default writable calendar from EventKit. |

- **Native bridge:** EventKit save; return stable **event identifier** and human-readable confirmation (title + local time range).

**Current implementation note (M4):** chat currently supports a deterministic structured form:
`create calendar event: title=...; starts_at=...; [ends_at=...; location=...; notes=...; all_day=true|false; calendar_id=...]`.
If `location` is missing, orchestration performs §3.4 step 1 (`calendar.search_past_events`) and either reuses a location or asks a focused follow-up.

### 3.2 Confirmation (recommended for v1)

Calendar writes are **high impact** and **time parsing can be wrong**. Recommended flow:

1. Tool returns a **proposed** event (or orchestrator emits a **pending** tool state).
2. Web UI shows a **confirmation card**: title, start/end, timezone, **location** (if any), calendar name — **Confirm** / **Edit** / **Cancel**.
3. On **Confirm**, bridge performs create; on **Edit**, user adjusts fields then confirm.

For **MVP**, a simpler path is allowed: create immediately after tool call, but the reply **must** state the parsed time explicitly so the user can correct (“That’s wrong—move it to 4pm”) in a follow-up if the product adds **update** later.

### 3.3 Errors

- **`PERMISSION_DENIED`:** Calendars not granted — chat message explains how to enable in **Settings → Permissions** with deep link.
- **`VALIDATION`:** Unparseable time — ask user for an explicit date/time.

### 3.4 Location reuse from prior visits (e.g. dentist)

When the user schedules a **recurring-style** appointment (dentist, doctor, salon, etc.) and does **not** provide a **place or address**, the agent should try to **reuse** the location from earlier context before creating the event.

**Recommended resolution order:**

1. **Past Calendar events (primary)**  
   - Invoke **`calendar.search_past_events`** (or equivalent) via EventKit: search **completed events** in a configurable lookback window (default e.g. **24 months**, not unbounded).  
   - Filter by **relevance** to the user’s wording: title/notes containing **keywords** (e.g. “dentist”, “dental”) or close variants from the model.  
   - Sort by **`starts_at` descending**; take the **most recent** event that has a non-empty **`location`** (or structured location).  
   - **Copy that `location` string** into the proposed `calendar.create_event` payload.

2. **Long-term memory (secondary)**  
   - If step 1 finds no suitable event or no location on matching events, run **`memory.search`** (or RAG retrieval) for the same intent, e.g. facts like “my dentist is Dr. X at …”, “Bright Smile Dental, 123 Main St.”  
   - If a **confident** address or place name appears in a chunk, use it as `location` (and optionally append a short note to `notes` citing “from saved memory”).

3. **Ask the user (fallback)**  
   - If still **no** location: **do not guess** a random address. Ask one focused question, e.g. *“I couldn’t find a previous dentist appointment with an address in your calendar or saved notes. What’s the **dentist or clinic name** (or full address)?”*  
   - After the user answers, **retry** step 2 if they gave a name only (search memory/calendar again with the new string), or use the provided **address** directly as `location`.  
   - Optionally offer **`memory.save`** to store “Dentist: Dr. X, 123 Main St.” for future reuse.

**Privacy:** **Memory and calendar-history lookups** for §3.4 stay **on-device** (FR-8). **No third-party geocoding API** is required for v1—user-supplied text is enough for Calendar’s `location` field. Optional **MapKit** name resolution is separate; see §3.5.

**UX:** The confirmation card (§3.2) should show **Location:** explicitly when filled, so the user can fix mistakes before **Confirm**.

### 3.5 Do you need MapKit to get an address from a name?

**No, not for a baseline.** EventKit stores `location` as a **string**. If the user says “Bright Smile Dental” or pastes a street address, you can set that string **without MapKit**; the system Calendar / Maps experience may still help the user later.

**Use MapKit when** you want the app to **resolve** a vague name into a **formatted address** (or coordinates) before saving—typically **`MKLocalSearch`** (or equivalent) in a **native** bridge. That path:

- Is **optional** for MVP; the §3.4 fallback (“ask for name or address”) remains valid without it.
- Usually involves **Apple’s location services** (often **network**). Disclose in product settings / privacy copy; it is **not** the same as sending chat or memory to a cloud LLM, but it is **not** purely offline.

**Summary:** **Name → address automation** → consider **MapKit** (or user edits the field manually). **Storing whatever text the user gave** → **no MapKit required**.

## 4. HTTP API (optional wrappers)

The orchestrator may call in-process services; exposing REST keeps CLI and tests aligned with [`client-api.md`](client-api.md).

### 4.1 `POST /memory/entries`

Already defined. Chat tools should reuse this contract.

### 4.2 `POST /calendar/events` (normative sketch)

`POST /api/v1/calendar/events`

Request:

```json
{
  "title": "Team sync",
  "starts_at": "2026-04-22T15:00:00-07:00",
  "ends_at": "2026-04-22T16:00:00-07:00",
  "all_day": false,
  "location": "123 Main St, City",
  "notes": "Optional description",
  "calendar_id": null
}
```

Response `201`:

```json
{
  "event_id": "ek-event-id-or-uuid",
  "title": "Team sync",
  "starts_at": "...",
  "ends_at": "..."
}
```

Errors: `401`, `403`/`PERMISSION_DENIED`, `422`/`VALIDATION`.

## 5. Tool registry & MCP

- Register **`memory.save`**, **`calendar.create_event`**, and **`calendar.search_past_events`** (read-only predicate over historical events for §3.4) in the tool registry with **capability checks** (NFR-4): calendar tools check **Calendars** permission before EventKit.
- **`calendar.search_past_events`** (conceptual schema): inputs such as `keywords[]`, `lookback_days` (default 730), `limit` (default 20); outputs a list of `{ event_id, title, starts_at, ends_at, location }` for **past** events only, ordered by `starts_at` descending.
- MCP exposure (if used) should mirror the same schemas for portability.

## 6. Related requirements

- [`requirement.md`](../../requirement.md): FR-3 (active entry), FR-6 (tools), FR-2 (EventKit)
- [`milestones.md`](milestones.md): M4 acceptance includes chat-triggered save and calendar create where feasible
