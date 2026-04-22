import AppKit
import CoreFoundation
import EventKit
import Foundation

/// Stdin JSON envelope:
/// - List: `{ "start", "end" }` or `{ "action":"list_events", "start", "end" }`
/// - Search: `{ "action":"search_past_events", "before", "keywords", "lookback_days"?, "limit"? }`
/// - Create: `{ "action":"create_event", "title", "starts_at", "ends_at"?, "all_day"?, "notes"?, "location"?, "calendar_id"? }`
/// Writes JSON to stdout: success payloads or `{ "ok": false, "error": { "code", "message" } }`
@main
enum Main {
    struct RequestEnvelope: Decodable {
        let action: String?
        let start: String?
        let end: String?
        let before: String?
        let lookback_days: Int?
        let keywords: [String]?
        let limit: Int?
        // create_event
        let title: String?
        let starts_at: String?
        let ends_at: String?
        let all_day: Bool?
        let notes: String?
        let location: String?
        let calendar_id: String?
    }

    static func main() {
        let inputData = FileHandle.standardInput.readDataToEndOfFile()
        guard !inputData.isEmpty else {
            emitError(code: "VALIDATION", message: "empty stdin")
            return
        }

        let env: RequestEnvelope
        do {
            env = try JSONDecoder().decode(RequestEnvelope.self, from: inputData)
        } catch {
            emitError(code: "VALIDATION", message: "invalid JSON envelope")
            return
        }

        let act = (env.action ?? "").lowercased()
        let mode: String
        if act.isEmpty {
            mode = (env.start != nil && env.end != nil) ? "list_events" : ""
        } else {
            mode = act
        }

        switch mode {
        case "list_events":
            runListEvents(env: env)
        case "search_past_events":
            runSearchPastEvents(env: env)
        case "create_event":
            runCreateEvent(env: env)
        default:
            emitError(
                code: "VALIDATION",
                message: "unknown or missing action; use list_events, search_past_events, or create_event",
            )
        }
    }

    // MARK: - list_events

    private static func runListEvents(env: RequestEnvelope) {
        guard let startStr = env.start, let endStr = env.end,
              !startStr.isEmpty, !endStr.isEmpty
        else {
            emitError(code: "VALIDATION", message: "list_events requires start and end (ISO-8601 strings)")
            return
        }

        let fmt = makeISOFormatter()
        guard let start = parseDate(startStr, fmt: fmt),
              let end = parseDate(endStr, fmt: fmt),
              start < end
        else {
            emitError(code: "VALIDATION", message: "invalid start/end or start >= end")
            return
        }

        let store = EKEventStore()
        guard ensureCalendarReadAccess(store: store) else { return }

        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)
        let raw = store.events(matching: predicate)
        let sorted = raw.sorted { $0.startDate < $1.startDate }
        emitEventsArray(sorted, outFmt: fmt)
    }

    // MARK: - search_past_events

    private static func runSearchPastEvents(env: RequestEnvelope) {
        guard let beforeStr = env.before, !beforeStr.isEmpty else {
            emitError(code: "VALIDATION", message: "search_past_events requires before (ISO-8601 instant)")
            return
        }
        let kws = (env.keywords ?? []).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        guard !kws.isEmpty else {
            emitError(code: "VALIDATION", message: "search_past_events requires non-empty keywords array")
            return
        }

        let lookbackDays = min(max(env.lookback_days ?? 730, 1), 3650)
        let limitN = min(max(env.limit ?? 20, 1), 100)

        let fmt = makeISOFormatter()
        guard let before = parseDate(beforeStr, fmt: fmt) else {
            emitError(code: "VALIDATION", message: "invalid before instant")
            return
        }

        guard let windowStart = Calendar.current.date(byAdding: .day, value: -lookbackDays, to: before) else {
            emitError(code: "VALIDATION", message: "invalid lookback window")
            return
        }

        let store = EKEventStore()
        guard ensureCalendarReadAccess(store: store) else { return }

        let predicate = store.predicateForEvents(withStart: windowStart, end: before, calendars: nil)
        var raw = store.events(matching: predicate)
        // Past-only: ended on or before reference instant
        raw = raw.filter { $0.endDate <= before }
        raw = raw.filter { ev in
            let hay = "\(ev.title ?? "")\n\(ev.notes ?? "")\n\(ev.location ?? "")"
            let lower = hay.lowercased()
            return kws.contains { lower.contains($0.lowercased()) }
        }
        raw.sort { $0.startDate > $1.startDate }
        raw = Array(raw.prefix(limitN))
        emitEventsArray(raw, outFmt: fmt, includeNotes: true)
    }

    // MARK: - create_event

    private static func runCreateEvent(env: RequestEnvelope) {
        guard let title = env.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else {
            emitError(code: "VALIDATION", message: "create_event requires title")
            return
        }
        guard let startsStr = env.starts_at, !startsStr.isEmpty else {
            emitError(code: "VALIDATION", message: "create_event requires starts_at (ISO-8601)")
            return
        }

        let fmt = makeISOFormatter()
        guard let startDate = parseDate(startsStr, fmt: fmt) else {
            emitError(code: "VALIDATION", message: "invalid starts_at")
            return
        }

        let allDay = env.all_day ?? false
        let endDate: Date
        if let es = env.ends_at, !es.isEmpty, let parsed = parseDate(es, fmt: fmt) {
            endDate = parsed
        } else {
            endDate = Calendar.current.date(byAdding: .hour, value: 1, to: startDate) ?? startDate.addingTimeInterval(3600)
        }
        guard startDate < endDate else {
            emitError(code: "VALIDATION", message: "ends_at must be after starts_at")
            return
        }

        let store = EKEventStore()
        guard ensureCalendarReadAccess(store: store) else { return }

        let cal: EKCalendar?
        if let cid = env.calendar_id, !cid.isEmpty {
            cal = store.calendar(withIdentifier: cid)
        } else {
            cal = store.defaultCalendarForNewEvents
        }
        guard let calendar = cal else {
            emitError(code: "VALIDATION", message: "no writable calendar (set calendar_id or check Calendar accounts)")
            return
        }

        let event = EKEvent(eventStore: store)
        event.calendar = calendar
        event.title = title
        event.isAllDay = allDay
        event.startDate = startDate
        event.endDate = endDate
        if let n = env.notes, !n.isEmpty { event.notes = n }
        if let loc = env.location, !loc.isEmpty { event.location = loc }

        do {
            try store.save(event, span: .thisEvent)
        } catch {
            emitOkFalse(code: "VALIDATION", message: "failed to save event: \(error.localizedDescription)")
            return
        }

        let outFmt = makeISOFormatter()
        let payload: [String: Any] = [
            "ok": true,
            "event_id": event.eventIdentifier ?? "",
            "title": title,
            "starts_at": outFmt.string(from: startDate),
            "ends_at": outFmt.string(from: endDate),
        ]
        emitJson(payload)
    }

    // MARK: - Shared emit

    private static func emitEventsArray(_ events: [EKEvent], outFmt: ISO8601DateFormatter, includeNotes: Bool = false) {
        var arr: [[String: Any]] = []
        for e in events {
            var row: [String: Any] = [
                "event_id": e.eventIdentifier ?? "",
                "title": e.title ?? "",
                "starts_at": outFmt.string(from: e.startDate),
                "ends_at": outFmt.string(from: e.endDate),
                "location": e.location ?? "",
                "all_day": e.isAllDay,
            ]
            if includeNotes, let n = e.notes, !n.isEmpty {
                let maxN = 2000
                row["notes"] = n.count > maxN ? String(n.prefix(maxN)) + "…" : n
            }
            arr.append(row)
        }
        emitJson(["ok": true, "events": arr])
    }

    // MARK: - Calendar access (read + write)

    private static func ensureCalendarReadAccess(store: EKEventStore) -> Bool {
        let sem = DispatchSemaphore(value: 0)
        var accessGranted = false
        var accessError: String?

        prepareForCalendarPermissionPrompt()
        RunLoop.current.run(until: Date().addingTimeInterval(0.15))

        if #available(macOS 14.0, *) {
            let status = EKEventStore.authorizationStatus(for: .event)
            switch status {
            case .fullAccess, .authorized:
                accessGranted = true
            case .denied, .restricted:
                accessGranted = false
            case .notDetermined, .writeOnly:
                DispatchQueue.main.async {
                    store.requestFullAccessToEvents { granted, err in
                        accessGranted = granted
                        if let err { accessError = err.localizedDescription }
                        sem.signal()
                    }
                }
                if !drainCalendarAccessWait(sem: sem) {
                    emitOkFalse(
                        code: "PERMISSION_DENIED",
                        message: "Timed out waiting for calendar access (no response from EventKit).",
                    )
                    return false
                }
            @unknown default:
                DispatchQueue.main.async {
                    store.requestFullAccessToEvents { granted, err in
                        accessGranted = granted
                        if let err { accessError = err.localizedDescription }
                        sem.signal()
                    }
                }
                if !drainCalendarAccessWait(sem: sem) {
                    emitOkFalse(
                        code: "PERMISSION_DENIED",
                        message: "Timed out waiting for calendar access (no response from EventKit).",
                    )
                    return false
                }
            }
        } else {
            DispatchQueue.main.async {
                store.requestAccess(to: .event) { granted, err in
                    accessGranted = granted
                    if let err { accessError = err.localizedDescription }
                    sem.signal()
                }
            }
            if !drainCalendarAccessWait(sem: sem) {
                emitOkFalse(
                    code: "PERMISSION_DENIED",
                    message: "Timed out waiting for calendar access (no response from EventKit).",
                )
                return false
            }
        }

        if !accessGranted {
            var msg = "Calendar access was not granted for MemoryAgent."
            if let accessError, !accessError.isEmpty { msg += " (\(accessError))" }
            logPermissionDeniedToStderr()
            emitOkFalse(code: "PERMISSION_DENIED", message: msg)
            return false
        }
        return true
    }

    private static func makeISOFormatter() -> ISO8601DateFormatter {
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fmt
    }

    private static func parseDate(_ s: String, fmt: ISO8601DateFormatter) -> Date? {
        if let d = fmt.date(from: s) { return d }
        let f2 = ISO8601DateFormatter()
        f2.formatOptions = [.withInternetDateTime]
        return f2.date(from: s)
    }

    private static func drainCalendarAccessWait(sem: DispatchSemaphore) -> Bool {
        let deadline = Date().addingTimeInterval(120)
        while true {
            switch sem.wait(timeout: .now() + .milliseconds(50)) {
            case .success:
                return true
            case .timedOut:
                let until = Date().addingTimeInterval(0.06)
                RunLoop.main.run(mode: .default, before: until)
                if Date() > deadline { return false }
            @unknown default:
                let until = Date().addingTimeInterval(0.06)
                RunLoop.main.run(mode: .default, before: until)
                if Date() > deadline { return false }
            }
        }
    }

    private static func prepareForCalendarPermissionPrompt() {
        let app = NSApplication.shared
        if !app.setActivationPolicy(.regular) {
            fputs("memoryagent-calendar: warning: setActivationPolicy(.regular) failed\n", stderr)
        }
        app.activate(ignoringOtherApps: true)
    }

    private static func logPermissionDeniedToStderr() {
        if #available(macOS 14.0, *) {
            let s = EKEventStore.authorizationStatus(for: .event)
            var hint = ""
            switch s {
            case .notDetermined:
                hint =
                    " Status stayed “not determined”: macOS may not have shown the prompt (common for CLI tools). Try: run the API/server from Terminal.app once, or run this binary directly in Terminal; then check System Settings → Privacy & Security → Calendars for Cursor or Terminal."
            case .denied:
                hint =
                    " Access denied. Open System Settings → Privacy & Security → Calendars and enable Calendar for Cursor, Terminal, or Python (whichever runs the server)."
            case .restricted:
                hint = " Access restricted (Screen Time / MDM). Relax restrictions or use another Mac user account."
            case .writeOnly:
                hint =
                    " Only write-only calendar access is granted; full read access is required. Grant full access in System Settings → Privacy & Security → Calendars."
            case .fullAccess, .authorized:
                hint = " Unexpected: access reported denied but authorization status looks granted; rebuild the calendar bridge and try again."
            @unknown default:
                hint =
                    " If the app still does not appear under Calendars, ensure you rebuilt this bridge after the Info.plist embed (see native-bridge/macos-calendar/Package.swift)."
            }
            fputs("memoryagent-calendar: authorizationStatus rawValue=\(s.rawValue).\(hint)\n", stderr)
        } else {
            fputs(
                "memoryagent-calendar: Calendar access denied. Grant access in System Settings → Privacy & Security → Calendars.\n",
                stderr,
            )
        }
    }

    static func emitError(code: String, message: String) {
        emitOkFalse(code: code, message: message)
    }

    static func emitOkFalse(code: String, message: String) {
        let payload: [String: Any] = [
            "ok": false,
            "error": [
                "code": code,
                "message": message,
            ],
        ]
        emitJson(payload)
    }

    static func emitJson(_ obj: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]),
              let s = String(data: data, encoding: .utf8)
        else {
            fputs("{\"ok\":false,\"error\":{\"code\":\"INTERNAL\",\"message\":\"json encode failed\"}}\n", stderr)
            return
        }
        print(s)
    }
}
