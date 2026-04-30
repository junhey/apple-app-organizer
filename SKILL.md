---
name: apple-app-organizer
description: This skill should be used when a user on macOS wants to clean up or organize built-in Apple applications — Messages (iMessage/SMS), Notes, Reminders, Calendar, Contacts, or Mail. It identifies clutter (spam conversations, duplicate notes, completed reminders, past events, duplicate contacts, promotional mail) and batch-removes or archives it using a safety-first workflow: dry-run by default, whitelist protection for legitimate data, trash-not-delete wherever possible, and 30-day undo via native recovery folders. Trigger phrases include 整理苹果, 清理信息, 清理备忘录, 删除过期日历, 合并重复联系人, 清理垃圾邮件, clean up Apple apps, tidy up iMessage, dedupe Notes, organize Reminders, purge old Calendar events, merge duplicate Contacts, archive old Mail. Requires macOS with Full Disk Access + Accessibility + Automation permissions for the invoking runtime.
description_zh: 苹果应用整理套件
description_en: Apple built-in app organizer
disable: false
agent_created: true
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

Scan `NoteStore.sqlite` to find duplicates and empties; archive via `Notes` AppleScript.

See [references/notes_store_schema.md](references/notes_store_schema.md) for table layout.

Pitfalls:
- Encrypted notes cannot be read — skipped automatically
- iCloud sync may lag up to 30s after archive
- `Archive` folder must exist; auto-created on first use

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
