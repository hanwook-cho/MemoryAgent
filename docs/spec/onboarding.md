# First-run chat welcome (onboarding)

When a user opens **Chat** for the **first time** on this browser profile, the UI must show a **static introduction** from the assistant—so new users understand what MemoryAgent is, what it can do, and how to start—**without** calling the chat LLM for this content (consistent copy, no token cost).

## 1. Behavior

| Rule | Detail |
| :--- | :--- |
| **Trigger** | Chat view loads, message history is empty, and the client has **not** recorded that the user has seen the welcome for this **major copy version** (see §2). |
| **Presentation** | Show the welcome as one or more **`assistant`** messages in the thread (same visual style as real replies), or an equivalent panel that clearly reads as the assistant speaking. |
| **Dismissal** | Treat the welcome as “seen” when the user **sends their first user message** and/or taps **Got it** / **Dismiss** (implement at least one path). |
| **No repeat** | After dismissal, do **not** auto-show the same welcome again unless the user chooses **Show welcome again** in Settings (optional but recommended). |
| **Copy updates** | Bump `WELCOME_COPY_VERSION` when the introduction text changes materially; returning users may see the new welcome once (see §2). |

## 2. Client persistence (recommended)

Use **`localStorage`** (same origin as the web app) so the welcome state survives refreshes without requiring a backend change:

| Key | Value | Purpose |
| :--- | :--- | :--- |
| `memoryagent.chatWelcome.dismissed` | `"true"` | User has completed first-run welcome for the current major copy version. |
| `memoryagent.chatWelcome.version` | string, e.g. `"1"` | Must match `WELCOME_COPY_VERSION` in §3; if the spec version bumps and stored version differs, show welcome again once. |

**Optional server parity:** `config.json` may mirror `ui.chat_welcome_dismissed` for consistency with CLI or multi-device use later; the web app can PATCH via [`http-api.md`](http-api.md) when implemented.

## 3. Canonical copy (user-facing)

**`WELCOME_COPY_VERSION`:** `3`

### 3.1 First message (short line)

Use as the opening line of the assistant introduction:

> Hi — I’m **MemoryAgent**, your **private memory assistant on this Mac**. I help you remember what you save and answer questions using **your** stored information—with **sources** when I rely on memory—while keeping **your data on your device** by default.

### 3.2 Second message (how to use)

Use as a follow-up assistant message or continuation (Markdown allowed in UI):

**What I can help with**

- **Save facts** — Tell me things to remember in chat (“Remember that …”), use quick entry, paste, or the memory controls in this app when available.
- **Ask questions** — I search what you’ve saved and reply in plain language; I’ll point to **what I used** when citations are available.
- **Schedule on your calendar** — With your permission, you can ask me to **add an event** to your Calendar (I’ll confirm the time when possible). For places you use often (e.g. dentist), I can **reuse the address** from a past visit or your saved notes when you don’t type it.
- **Work offline** — Core chat is designed to run **locally** on your Mac without needing a cloud AI service for normal use.
- **Connect what you allow** — Over time you can let me use **folders you choose** and, with permission, **Calendar/Reminders**. I don’t silently read your entire Mac.

**Good prompts to try**

- “What have I saved about [topic]?”
- “Remember: [something important].”
- “Put [title] on my calendar [day] at [time].”
- “Summarize what you know about [project].”

If you tell me what you’re using this for—work, school, health, planning—I can suggest a simple workflow.

---

Implementations may merge §3.1 and §3.2 into a **single** assistant bubble if the layout works better; keep the **same** wording unless the product team updates this file and `WELCOME_COPY_VERSION`.

## 4. Settings (optional)

- **Show welcome again** — Clears `memoryagent.chatWelcome.dismissed` (and optionally sets version to current) so the next empty chat shows the introduction.
- **Permissions** — Link to [`permissions-matrix.md`](permissions-matrix.md) UX: explain that calendar/file features appear as the user enables each capability.

## 5. Related requirements

- [`requirement.md`](../../requirement.md) **UI-5**
- [`milestones.md`](milestones.md) **M1** (first-run welcome acceptance)
- [`agent-actions.md`](agent-actions.md) (memory save, calendar create, location reuse — reflected in welcome copy when `WELCOME_COPY_VERSION` ≥ 2; place reuse line when ≥ 3)
