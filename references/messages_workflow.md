# Messages Module Workflow

> Full procedural guide for cleaning up iMessage / SMS conversations in Messages.app.

## Overview

Messages cleanup happens in three phases:

1. **Scan** — Read `~/Library/Messages/chat.db` read-only and classify every chat
2. **Review** — User inspects the Markdown report and confirms the delete list
3. **Batch delete** — UI automation walks the sidebar, deleting one chat at a time

## Phase 1: scan

```bash
python3 scripts/organize.py messages scan
```

Output locations (default):
- `/tmp/apple-app-organizer/messages-report-YYYYMMDD-HHMMSS.json`
- `/tmp/apple-app-organizer/messages-report-YYYYMMDD-HHMMSS.md`

### Classification rules

| Label | Rule |
|-------|------|
| `normal` | Matches `+86\d{11}`, `+1\d{10}`, `+44\d{10}`, `+81\d{10,11}`, OR in bank-short-code whitelist (95588/95555/95533/95559/95566/95577/95595/95522), OR 121234403 |
| `spam` | Starts with prefix 106/955/10010/10086/10000/10001/12306/59239/59200/400/800, OR last message matches spam keyword, OR numeric id ≥ 12 digits |
| `unknown` | 4-6 digit short code, OR email, OR anything uncategorized |

All rules live in `scripts/modules/common.py` and are unit-tested.

## Phase 2: review

Open the Markdown report:

```bash
open /tmp/apple-app-organizer/messages-report-*.md
```

For each `unknown` entry, decode the actual message content to decide:

```bash
# Use the companion imessage-query skill
python3 ~/.workbuddy/skills/imessage-query/scripts/decode_attributed_body.py \
    --chat "<CHAT_IDENTIFIER>" --limit 1 --order desc
```

Add any `unknown` entries you want to delete to `to-delete.json`:

```bash
python3 - <<'PY'
import json
report = json.load(open(sorted(__import__("glob").glob("/tmp/apple-app-organizer/messages-report-*.json"))[-1]))
to_delete = [e["chat_id"] for e in report["spam"]]
# plus any unknown entries you want:
to_delete += ["1001291"]
json.dump(to_delete, open("/tmp/apple-app-organizer/to-delete.json", "w"))
PY
```

## Phase 3: batch delete

```bash
# Dry-run first
python3 scripts/organize.py messages clean --dry-run

# Execute (only after dry-run looks right)
python3 scripts/organize.py messages clean --execute
```

### How it works

Messages.app has a useful property: after you delete a chat in **standalone
chat window mode**, it auto-advances to the next chat in the sidebar. We
exploit this:

1. `_current_window_name()` reads the title of `window 1` = currently selected chat id
2. If protected → press `Cmd+Shift+]` to advance (fallback `Cmd+Shift+[`)
3. If in delete list or matches inline spam rules → invoke menu "对话 → 删除对话…", click strict-match button `title is "删除"`
4. Messages auto-advances; loop continues
5. If uncertain (neither protected nor targeted) → **halt** and report for user review

### Guardrails

- `_clear_pending_sheet()` at loop head cancels any lingering confirmation dialog
- Loop detection: 5 identical `window 1` titles in a row → halt
- Per-iteration whitelist check — UI might have advanced unexpectedly
- Strict `title is "删除"` matching avoids the "删除并报告垃圾信息" button (would also report number to Apple)
- `keep_exact` parameter lets callers extend the whitelist with specific short codes

## Recovery

Deleted conversations enter **显示 → 最近删除** (`Cmd+3` in Messages). Retained 30 days.

Restore via UI:
1. Messages.app → menu "显示 → 最近删除"
2. Select conversation(s)
3. Click **恢复** button

## Known pitfalls

### Chinese input

```applescript
-- WRONG: produces garbled bytes
keystroke "瑞幸咖啡"

-- RIGHT: use clipboard
set the clipboard to "瑞幸咖啡"
keystroke "v" using command down
```

### Phone number format mismatch

- In UI window title: `+86 187 7391 0065` (with spaces)
- In chat.db: `+8618773910065` (no spaces)

Always call `common.normalize_phone()` before whitelist matching.

### Confirmation sheet has 3 buttons

Modern Messages sheets: `[删除, 删除并报告垃圾信息, 取消]`. Strict `is "删除"` match. Do NOT use `starts with "删除"`.

### No keyboard shortcut for Delete Conversation

The menu item `对话 → 删除对话…` has `AXMenuItemCmdChar = missing value`. Must invoke via `click menu item`.

### "In New Window" traps the sidebar

If the user (or script) ever triggers `文件 → 在新窗口中打开对话`, Messages.app remembers this and subsequent launches may open standalone windows without a sidebar. Recovery:

```bash
killall Messages
rm -rf ~/Library/Saved\ Application\ State/com.apple.MobileSMS.savedState
sleep 2
open -a Messages
```

Or: Dock right-click "信息" → Quit → relaunch from Launchpad.

### chat.db is soft-delete

Deletion moves rows to `chat_recoverable_message_join` (30-day cache) — `chat` row stays. So:
- `SELECT COUNT(*) FROM chat` does NOT drop after deletion
- `tell application "Messages" to return count of chats` returns a cached value that may lag
- **Truth source**: UI sidebar state

## Testing this module locally

```bash
cd ~/.workbuddy/skills/apple-app-organizer
python3 -m venv venv && source venv/bin/activate
pip install pytest
pytest tests/test_messages.py -v
# All tests should pass without any real chat.db or Messages.app access.
```
