# Permissions and capability matrix

macOS capabilities should be requested **only when a feature needs them** (NFR-4). The web app surfaces status; the core service or native bridge performs `TCC` prompts when possible.

## 1. Matrix

| Feature | Capability | When to prompt | If denied |
| :--- | :--- | :--- | :--- |
| Index user-chosen folders under home | Files and Folders (per-directory) or Full Disk Access | First time user adds a path outside sandbox | Show inline error; offer “Open System Settings” deep link |
| File watcher for `Documents` / `Desktop` | Same as above | When enabling watch roots | Disable watcher for that path |
| Calendar read (query upcoming events) | Calendars | First **read** tool use | Tool returns structured error; chat explains limitation |
| Calendar create (add event) | Calendars | First tool that **creates** an event (often same system prompt as read on macOS) | Offer confirmation UI when possible per [`agent-actions.md`](agent-actions.md); on deny, same as read |
| Reminders | Reminders | First reminder tool use | Same as calendars |
| Notes (if using Scripting) | Automation for Notes | First Notes action | Fall back to export-based ingestion only if implemented |
| Mail (deferred) | IMAP or provider API with user credentials in Keychain | If/when email ingestion is implemented | Not Mail.app scraping; document account-based setup |
| iMessage, Apple Journal (out of scope v1) | N/A as baseline | Do not prompt for Full Disk Access solely for these | Rely on user export or future Apple APIs if product scope expands |
| Accessibility | Only if global hotkey or UI automation | Optional native companion | Disable that feature |

## 2. UX in the web app

- **Settings → Permissions:** Show each capability with state: `not requested`, `granted`, `denied`, `restricted`.
- **No silent failures:** Tool errors must map to user-visible messages and permission hints.

## 3. CLI parity

CLI commands that touch protected data must check the same capability layer and exit with actionable stderr.
