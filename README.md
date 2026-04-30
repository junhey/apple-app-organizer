# apple-app-organizer

> Safe, dry-run-first cleanup suite for macOS built-in apps.

[![Python 3.13](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![macOS only](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Features

| App | What it cleans | Safety |
|-----|---------------|--------|
| **Messages** | Spam/promotional iMessage/SMS conversations | Recently Deleted (30 days) |
| **Notes** | Duplicate & empty notes | Archive folder |
| **Reminders** | Completed/overdue old reminders | ⚠️ Irreversible |
| **Calendar** | Past events, recurring duplicates | ⚠️ Irreversible |
| **Contacts** | Duplicate contacts (phone/email) | Manual merge in UI |
| **Mail** | Promotional & old-unread messages | Trash (30 days) |

## Quick Start

```bash
# 1. Clone & install
git clone https://github.com/junhey/apple-app-organizer.git
cd apple-app-organizer
pip install -r requirements.txt

# 2. Grant permissions (System Settings → Privacy & Security → Automation)
#    Enable: Contacts, Calendar, Reminders, Notes, Mail, Messages

# 3. Scan all modules (dry-run — no changes)
python3 scripts/organize.py messages scan
python3 scripts/organize.py contacts scan
python3 scripts/organize.py mail scan

# 4. Generate a Markdown report for review
python3 scripts/organize.py contacts report --output-dir ./reports
python3 scripts/organize.py mail report --output-dir ./reports

# 5. Clean up (dry-run by default)
python3 scripts/organize.py mail clean --mailbox "INBOX" --dry-run

# 6. Actually execute (requires explicit flag)
python3 scripts/organize.py mail clean --mailbox "INBOX" --execute --yes
```

## Safety Principles

1. **Dry-run by default** — Every command reads-only until you pass `--execute`
2. **Whitelist protection** — Edit `whitelist.json` to protect real contacts/calendars
3. **Trash, not delete** — Mail → Trash; Messages → Recently Deleted; Notes → Archive
4. **No automatic Contacts merge** — Manual merge via Contacts.app UI required
5. **Reminders/Calendar are irreversible** — Requires explicit `--execute --yes`

## Feature Matrix

```
Module      | Scan | Report | Clean | Requires FDA | Requires Automation
------------|------|--------|-------|-------------|---------------------
Messages    |  ✅  |   ✅   |  ✅   |     Yes      |        Yes
Notes       |  ✅  |   ✅   |  ✅   |     Yes      |        Yes
Reminders   |  ✅  |   ✅   |  ✅   |     No       |        Yes
Calendar    |  ✅  |   ✅   |  ✅   |     No       |        Yes
Contacts    |  ✅  |   ✅   |  ⚠️   |     No       |        Yes
Mail        |  ✅  |   ✅   |  ✅   |     No       |        Yes
```

FDA = Full Disk Access (needed for SQLite databases: messages/notes)

## Configuration

### Whitelist

Edit `whitelist.json` to protect specific identifiers:

```json
{
  "phone_numbers": ["+86 138 0000 0000"],
  "email_addresses": ["trusted@example.com"],
  "calendar_names": ["Birthdays", "Holidays"],
  "contact_ids": ["ABC-DEF-123"]
}
```

### Output directory

```bash
python3 scripts/organize.py contacts report --output-dir ./my-reports
```

## License

MIT License — see [LICENSE](LICENSE)
