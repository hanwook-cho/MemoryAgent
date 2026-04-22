# macOS Calendar bridge (EventKit)

Small **stdin/stdout JSON** helper used by the core service for **`calendar.list_events`**.

## Build

```bash
cd native-bridge/macos-calendar
swift build -c release
```

Binary: `.build/<arch>-apple-macosx/release/memoryagent-calendar`

## Run (manual)

List events in a window (backward-compatible; `action` optional):

```bash
echo '{"action":"list_events","start":"2026-04-21T00:00:00Z","end":"2026-04-28T23:59:59Z"}' | .build/*/release/memoryagent-calendar
```

Search past events for keywords (title/notes/location):

```bash
echo '{"action":"search_past_events","before":"2026-04-28T12:00:00Z","keywords":["dentist"],"lookback_days":730,"limit":10}' | .build/*/release/memoryagent-calendar
```

Create an event:

```bash
echo '{"action":"create_event","title":"Test","starts_at":"2026-05-01T15:00:00Z","ends_at":"2026-05-01T16:00:00Z"}' | .build/*/release/memoryagent-calendar
```

First run may prompt for **Calendars** access in System Settings.

## Configure core

Point the core at the binary (optional if the default repo-relative path exists):

```bash
export MEMORYAGENT_CALENDAR_BRIDGE="/path/to/memoryagent-calendar"
```
