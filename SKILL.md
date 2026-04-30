---
name: apple-app-organizer
description: "This skill should be used when a user on macOS wants to clean up or organize built-in Apple applications — Messages (iMessage/SMS), Notes, Reminders, Calendar, Contacts, or Mail. It identifies clutter (spam conversations, duplicate notes, completed reminders, past events, duplicate contacts, promotional mail) and batch-removes or archives it using a safety-first workflow — dry-run by default, whitelist protection for legitimate data, trash-not-delete wherever possible, and 30-day undo via native recovery folders. Trigger phrases include 整理苹果, 清理信息, 清理备忘录, 删除过期日历, 合并重复联系人, 清理垃圾邮件, clean up Apple apps, tidy up iMessage, dedupe Notes, organize Reminders, purge old Calendar events, merge duplicate Contacts, archive old Mail. Requires macOS with Full Disk Access, Accessibility, and Automation permissions for the invoking runtime."
license: MIT
---

# apple-app-organizer

A TDD-built cleanup suite for macOS's built-in applications. Every destructive
operation defaults to dry-run; every module enforces a whitelist and prefers
reversible actions (trash / archive / recently-deleted) over hard delete.

## When to use

Use this skill when a user requests any of:
- "帮我整理 iMessage / 信息 / 短信"
- "清理备忘录里的重复笔记"
- "删除已完成的提醒事项"
- "清空过期的日历事件"
- "合并通讯录里的重复联系人"
- "清理邮件里的广告"
- or general phrases like "整理 Mac / clean up my Mac apps"

Do NOT use for:
- Third-party apps (WeChat, WhatsApp, Outlook, Gmail web, etc.)
- Anything on iOS directly (this is macOS-only; iCloud-synced changes will propagate)
- Irreversible system-wide cleanup (disk usage, cache files — use a different tool)

## Safety principles (read before every run)

1. **Dry-run by default.** Every CLI subcommand starts in `--dry-run` mode; `--execute` is required to mutate.
2. **Whitelist enforcement.** Real phone contacts, trusted short codes, primary email accounts are never touched.
3. **Trash, not delete.** Mail → Trash; Messages → Recently Deleted (30 days); Notes → Archive folder; Reminders → direct delete only after user confirms.
4. **Per-item confirmation** available via `--confirm-each`.
5. **Report first.** Every module can emit a Markdown report for user review before any write happens.
6. **Loop detection.** UI-automation loops halt after 5 identical window titles to prevent runaway keypresses.

## Prerequisites

### 1. Full Disk Access

Required to read `chat.db`, `NoteStore.sqlite`, and other sandboxed system databases.

```bash
# Verify
sqlite3 -readonly ~/Library/Messages/chat.db "SELECT COUNT(*) FROM chat;"
```

Grant via **System Settings → Privacy & Security → Full Disk Access**. Add `Terminal.app` and the agent's runtime (Cursor, Claude Code, WorkBuddy, Warp, etc.). **Completely relaunch** the runtime after granting.

### 2. Accessibility

Required for UI automation (Messages deletion via menu clicks).

```bash
osascript -e 'tell application "System Events" to get UI elements enabled'   # must be true
```

### 3. Automation (per-app prompts)

On first run, macOS will prompt: **"X wants to control Messages/Notes/Reminders/Calendar/Contacts/Mail"**. Click **OK** for each.

Verify via **System Settings → Privacy & Security → Automation**.

## Modules

| Module | Data source | Workflow | Status |
|--------|-------------|----------|--------|
| [Messages](#messages) | `~/Library/Messages/chat.db` + Messages.app UI | Spam classification → batch delete (Recently Deleted) | ✅ v1.0 |
| [Notes](#notes) | `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` + Notes.app AS | Duplicate/empty detection → archive or delete | ✅ v1.0 |
| [Reminders](#reminders) | Reminders.app AS | Completed/overdue scan → bulk delete | ✅ v1.0 |
| [Calendar](#calendar) | Calendar.app AS | Past events → purge; recurring duplicates → merge | ✅ v1.0 |
| [Contacts](#contacts) | Contacts.app AS | Phone/email duplicates → manual merge report | ✅ v1.0 |
| [Mail](#mail) | Mail.app AS | Ad classification → move to Trash | ✅ v1.0 |

## Unified CLI

```bash
python3 scripts/organize.py <module> [scan|report|clean] [flags]
```

Examples:

```bash
# Scan everything
python3 scripts/organize.py messages scan
python3 scripts/organize.py notes scan --include-body

# Generate Markdown report
python3 scripts/organize.py reminders report --older-than-days 30

# Dry-run clean (prints planned actions, doesn't mutate)
python3 scripts/organize.py calendar clean --older-than-months 12 --dry-run

# Actually execute (requires explicit --execute)
python3 scripts/organize.py mail clean --mailbox "Junk" --execute --yes
```

Common flags:
- `--dry-run` (default) / `--execute` — must pass `--execute` to mutate
- `--output-dir PATH` — where reports are written (default `/tmp/apple-app-organizer/`)
- `--yes` — skip interactive per-item confirmation
- `--whitelist-file PATH` — JSON array of identifiers to protect

## Messages

Scan `chat.db` and batch-delete spam conversations while protecting real contacts.

See [references/messages_workflow.md](references/messages_workflow.md) for:
- Full workflow (scan → review → delete → verify)
- Chinese number classification rules
- Recovery procedure (Recently Deleted, 30 days)

Key pitfalls (lessons learned):
- Messages AppleScript `delete` command is broken (error -10000) — use menu UI only
- Menu item "删除对话…" has no keyboard shortcut — must be invoked via `click menu item`
- Chinese input requires clipboard + `Cmd+V`, not `keystroke`
- Confirmation sheet has **three** buttons `[删除, 删除并报告垃圾信息, 取消]` — match `title is "删除"` strictly
- Chinese mobile numbers appear with spaces in window titles (`+86 187 7391 0065`) but without spaces in `chat.db` — normalize before whitelist match

## Notes

Scan `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` to find
duplicates and empty notes; archive or delete via Notes AppleScript.

See [references/notes_store_schema.md](references/notes_store_schema.md) for the full
table layout and decoding strategy.

### Prerequisites

- **Full Disk Access** — required to read the Group Container sandbox
  ```bash
  sqlite3 -readonly ~/Library/Group\ Containers/group.com.apple.notes/NoteStore.sqlite \
    "SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT IN (5,11,12);"
  ```
- **Automation permission** — System Settings → Privacy & Security → Automation →
  enable **Notes** (the agent will be prompted on first run)

### Workflow

```bash
# Scan all notes (shows duplicates, empties, metadata)
python3 scripts/organize.py notes scan

# Find duplicate notes
python3 scripts/organize.py notes scan --include-body

# Archive duplicate notes (dry-run first)
python3 scripts/organize.py notes clean --action archive --older-than-days 30 --dry-run

# Delete empty notes (requires --execute)
python3 scripts/organize.py notes clean --action delete-empty --min-chars 5 --dry-run
python3 scripts/organize.py notes clean --action delete-empty --min-chars 5 --execute --yes
```

### API (scripts/modules/notes.py)

```python
from modules.notes import list_folders, scan_notes, detect_duplicates, detect_empty, archive_note, delete_note

folders = list_folders()
notes = scan_notes()
dup_groups = detect_duplicates()   # [[uuid, uuid, ...], ...]
empty = detect_empty(min_chars=10)  # [uuid, ...]
archive_note(uuid)                   # safe, icloud-synced
delete_note(uuid, dry_run=True)     # dry-run guard; set dry_run=False to execute
```

### Pitfalls

- **Encrypted notes** (`ZISPASSWORDPROTECTED=1`) cannot be read — they are
  automatically excluded from body scans and `detect_empty()`. They appear in
  `scan_notes()` with `is_encrypted: True` and `body_preview: ""`.
- **Body decoding**: note text is stored as a gzip-compressed protobuf with
  UTF-8 text interleaved with binary structure bytes. The module uses
  `errors='ignore'` UTF-8 decoding to strip proto bytes, then extracts readable
  sequences via regex. Short words (2–3 chars) may occasionally be dropped.
- **iCloud sync lag**: AppleScript changes (archive/delete) sync to iCloud within
  ~30 seconds. Re-scanning immediately after an action may show stale data.
  Add a `time.sleep(1)` delay in scripts that chain scan + mutate.
- **`Archive` folder**: created automatically on first `archive_note()` call if
  it does not exist.
- **Notes.app must be open** (or at least not blocking automation) for AppleScript
  operations to succeed. Errors are raised as `AppleScriptError` with stderr.

### Module status

| Function | Status |
|----------|--------|
| `list_folders()` | ✅ v1.0 |
| `scan_notes()` | ✅ v1.0 |
| `detect_duplicates()` | ✅ v1.0 |
| `detect_empty()` | ✅ v1.0 |
| `archive_note()` | ✅ v1.0 |
| `delete_note()` | ✅ v1.0 (dry-run default) |

## Reminders

Enumerate lists, detect overdue and long-completed items, bulk delete.

See [references/eventkit_applescript.md](references/eventkit_applescript.md).

## Calendar

Detect events older than N months; flag orphaned recurring siblings.

See [references/eventkit_applescript.md](references/eventkit_applescript.md).

## Contacts

Detect duplicate contacts by normalized phone or case-insensitive email. Emit
Markdown merge report (Contacts.app has no scriptable merge verb; user performs
merge in UI using the generated report).

## Mail

Classify promotional/ad emails by sender + keyword rules; move to Trash for
30-day reversible recovery.

## Verification after cleanup

```bash
# Messages — protected contacts intact?
python3 scripts/organize.py messages verify --whitelist-file my-contacts.json

# Everything — summarize what changed
python3 scripts/organize.py status
```

## Further reading

- [references/messages_workflow.md](references/messages_workflow.md)
- [references/notes_store_schema.md](references/notes_store_schema.md)
- [references/eventkit_applescript.md](references/eventkit_applescript.md)
- [references/applescript_recipes.md](references/applescript_recipes.md)
- [references/permissions_guide.md](references/permissions_guide.md)
