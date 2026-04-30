# EventKit / AppleScript Reference for Reminders & Calendar

Both Reminders.app and Calendar.app expose Apple's EventKit data via AppleScript
dictionaries. This skill uses only AppleScript (no private EventKit headers).

## Permissions

First use will prompt for:
- **Automation permission** to control Reminders or Calendar
- **Reminders access** (separate OS prompt, once per runtime)
- **Calendar access** (separate OS prompt, once per runtime)

Verify in **System Settings → Privacy & Security → Automation** and **Reminders / Calendars**.

## Reminders.app

### Dictionary extracts

```applescript
-- Top-level
tell application "Reminders"
    lists                        -- all lists
    reminders                    -- all reminders across all lists
    reminder "<name>" of list "<ln>"
end tell

-- Per-list
tell application "Reminders"
    set lst to list "Inbox"
    reminders of lst
    count of reminders of lst
    reminders of lst whose completed is true
    reminders of lst whose completed is false
end tell

-- Reminder object properties (read)
name, body, completed, completion date, due date, priority, flagged, id
```

### Enumerate all completed reminders older than cutoff

```applescript
tell application "Reminders"
    set cutoff to (current date) - (30 * days)
    set out to ""
    repeat with lst in lists
        repeat with r in (reminders of lst whose completed is true)
            try
                set d to completion date of r
                if d is not missing value and d < cutoff then
                    set out to out & (id of r as string) & tab & (name of r) & tab & (d as string) & tab & (name of lst) & linefeed
                end if
            end try
        end repeat
    end repeat
    return out
end tell
```

### Delete by id

```applescript
tell application "Reminders"
    delete (first reminder whose id is "x-apple-reminderkit://REMCDReminder/...")
end tell
```

### Pitfalls

- `current date` returns local time; cutoffs are in seconds (not days). Multiply `30 * days` (`days` is a constant keyword).
- Some reminders (synced from CalDAV servers) may have `missing value` for `completion date` even when `completed is true`. Wrap in `try` and treat missing as "unknown age".
- List names can contain emojis — quoting them inline in AppleScript is unreliable, use `whose name is` filter instead.
- Very large lists (>1000 items) can time out the default `osascript` 15s. Bump `timeout=60` for full scans.

## Calendar.app

### Dictionary extracts

```applescript
tell application "Calendar"
    calendars
    events of calendar "Home"
    event "<title>" of calendar "Home"
end tell

-- Event object properties (read)
summary, description, location, start date, end date, all day event, uid, recurrence
```

### Enumerate past events

```applescript
tell application "Calendar"
    set cutoff to (current date) - (6 * 30 * days)
    set out to ""
    repeat with cal in calendars
        repeat with e in (events of cal whose start date < cutoff)
            set out to out & (uid of e as string) & tab & (summary of e as string) & tab & (start date of e as string) & tab & (name of cal as string) & linefeed
        end repeat
    end repeat
    return out
end tell
```

### Delete by uid

```applescript
tell application "Calendar"
    tell calendar "Home"
        delete (first event whose uid is "CAFE-1234-...")
    end tell
end tell
```

### Pitfalls

- **Recurring event behavior is treacherous.** A single "master" event with a recurrence rule has many "detached" instances. Deleting the master does NOT delete historical modified instances. For robust recurring cleanup, enumerate instances by `uid` and delete each individually.
- **All-day events have TZ quirks.** `start date of e` for an all-day event returns midnight in the system timezone; a VALUE at 00:00:00 may legitimately precede or follow a cutoff by hours depending on DST transitions.
- **iCloud calendars sync asynchronously.** A deleted event may reappear for 10-60 seconds before the CalDAV server acknowledges. Do not immediately re-enumerate to verify deletion.
- **Holiday/subscribed calendars are read-only.** `delete event` will silently fail. Always check with `writable of cal` first, or (simpler) use `whitelist_calendars` to skip them.
- **The `uid` is stable across devices** but Calendar.app sometimes rewrites it after sync — do not cache uids across long-running sessions.

### Finding duplicate recurring siblings

Sometimes a recurring event gets duplicated (e.g., a CalDAV sync glitch):
both copies have the same summary and same start time but different uids.
This skill's `detect_recurring_duplicates()` groups events by
`(summary, start_date)` and flags any group with >1 entries.

```python
groups = calendar.detect_recurring_duplicates()
for group in groups:
    print(f"Duplicate: {group[0]['summary']} on {group[0]['start_date']}")
    for event in group[1:]:  # keep first, delete rest
        calendar.delete_event(event["id"], event["calendar"], dry_run=False)
```

## Performance

- Reminder-heavy users (1000+): `list_completed()` can take 20-40s. Timeout set to 60s.
- Calendar-heavy users (10k+ events): `list_past_events()` timeout 120s; limit per-calendar cap of 500 rows by default.
- AppleScript output is tab-separated one row per record. Never use comma — summaries/names frequently contain commas.

## Recovery

- **Reminders**: there is NO "Recently Deleted" folder. `delete reminder` is PERMANENT. Always `--dry-run` first, and encourage users to confirm the Markdown report before executing.
- **Calendar**: `delete event` is also permanent (Calendar.app has no trash). Same caveat — always dry-run. Users can theoretically recover via Time Machine or an iCloud.com rollback (last 30 days) but this is not something the skill can offer directly.
