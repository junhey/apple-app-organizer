# apple-app-organizer

[![tests](https://img.shields.io/badge/tests-129%20passing-brightgreen)](./tests)
[![modules](https://img.shields.io/badge/modules-6-blue)](#modules)
[![license](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![skill](https://img.shields.io/badge/agent-skill-purple)](https://skills.sh)

A TDD-built, safety-first cleanup suite for macOS's built-in applications.

**v1.0.0 — All 6 modules complete.**

## Feature matrix

| Module | Scan | Report | Clean | Safety net | Tests |
|--------|------|--------|-------|-----------|-------|
| **Messages** | ✅ | ✅ | ✅ | Recently Deleted (30d) | 13 |
| **Notes** | ✅ | ✅ | ✅ (via AppleScript) | Move to Archive folder | 26 |
| **Reminders** | ✅ | ✅ | ✅ | Permanent — always dry-run first | 16 |
| **Calendar** | ✅ | ✅ | ✅ | Permanent — whitelist required | 14 |
| **Contacts** | ✅ | ✅ | ⚠️ manual merge | Report-only | 15 |
| **Mail** | ✅ | ✅ | ✅ | Move to Trash (30d) | 11 |

Plus **common utilities** (whitelist / spam rules / report writers): 21 tests.  
**Integration tests** (CLI subprocess): 12 tests.  
**Total: 129 tests, all green.**

## Install

```bash
# Via skills CLI (recommended)
npx skills add junhey/apple-app-organizer

# Or clone
git clone https://github.com/junhey/apple-app-organizer ~/.workbuddy/skills/apple-app-organizer
```

## Prerequisites

1. **Full Disk Access** — Terminal.app + agent runtime (Cursor, WorkBuddy, Claude Code, Warp, …)
2. **Accessibility** — same runtime
3. **Automation permission** — granted per-app on first prompt

See [`references/permissions_guide.md`](./references/permissions_guide.md) for step-by-step.

## Quickstart

```bash
# Run the TDD test suite
cd ~/.workbuddy/skills/apple-app-organizer
python3 -m pytest tests/ -v    # 129 tests

# Unified CLI
python3 scripts/organize.py <module> <action> [flags]
```

### Example flows

```bash
# Messages — classify and report
python3 scripts/organize.py messages scan
python3 scripts/organize.py messages report

# Messages — dry-run clean, then execute
python3 scripts/organize.py messages clean               # dry-run by default
python3 scripts/organize.py messages clean --execute --yes

# Notes — find duplicates and empty notes
python3 scripts/organize.py notes report --min-chars 10

# Reminders — purge completed older than 30 days
python3 scripts/organize.py reminders clean --older-than-days 30 --execute

# Calendar — report past events, excluding birthdays
python3 scripts/organize.py calendar report \
    --older-than-months 12 --exclude Birthdays "US Holidays"

# Contacts — detect duplicates and generate merge report
python3 scripts/organize.py contacts report

# Mail — trash ads in Junk mailbox
python3 scripts/organize.py mail clean \
    --mailbox Junk --account "iCloud" --execute --yes
```

## Safety principles

1. **Dry-run by default** — every mutating subcommand requires `--execute`
2. **Whitelist first** — real phone numbers and bank short codes are never deleted
3. **Trash, not delete** — Mail→Trash, Messages→Recently Deleted, Notes→Archive
4. **Report first** — every module can emit a Markdown report for user review
5. **Loop detection** — UI automation halts after 5 identical window titles
6. **Per-iteration window-title validation** — catches mid-run UI changes
7. **Strict sheet matching** — `title is "删除"` exactly (avoids "删除并报告" dual-action button)

## Architecture

```
apple-app-organizer/
├── SKILL.md                    # Agent-facing entry point
├── README.md                   # User-facing docs
├── LICENSE                     # MIT
├── pytest.ini
├── scripts/
│   ├── organize.py             # Unified CLI
│   └── modules/
│       ├── common.py           # osa(), whitelist, report writers
│       ├── messages.py         # iMessage/SMS via chat.db + UI
│       ├── notes.py            # Notes via NoteStore.sqlite + AS
│       ├── reminders.py        # Reminders via AS
│       ├── calendar.py         # Calendar via AS
│       ├── contacts.py         # Contacts via AS (report-only)
│       └── mail.py             # Mail via AS (trash-not-delete)
├── references/
│   ├── permissions_guide.md
│   ├── messages_workflow.md
│   ├── chat_db_schema.md
│   ├── notes_store_schema.md
│   ├── eventkit_applescript.md
│   └── applescript_recipes.md
└── tests/
    ├── conftest.py             # Fixtures (fake chat.db, fake NoteStore.sqlite)
    ├── test_common.py          # 21 tests
    ├── test_messages.py        # 13 tests
    ├── test_notes.py           # 26 tests
    ├── test_reminders.py       # 16 tests
    ├── test_calendar.py        # 14 tests
    ├── test_contacts.py        # 15 tests
    ├── test_mail.py            # 11 tests
    └── test_integration.py     # 12 tests (CLI subprocess)
```

## TDD & testing

```bash
python3 -m venv venv && source venv/bin/activate
pip install pytest
pytest tests/ -v --tb=short

# Only run a specific module's tests
pytest tests/test_notes.py -v

# With coverage
pip install pytest-cov
pytest --cov=scripts.modules tests/
```

All modules follow the same test strategy:
- **Unit tests**: mock `common.osa` so no real Mail/Messages/etc. is touched
- **Fixture data**: `conftest.py` builds a temporary SQLite that mimics real chat.db / NoteStore.sqlite schemas
- **Integration tests**: invoke `organize.py` in a subprocess to validate argparse + module resolution

## TDD iteration history

| # | Time | Scope | Tests added | Commit |
|---|------|-------|-------------|--------|
| 1 | 22:00 | Skeleton + Messages module | 34 | `1c0afe2 feat: initial skeleton + messages module` |
| 2 | 22:30 | Notes module (auto-scheduled) | 26 → 60 | `a7877cf feat(notes): scanner + duplicate detector + safe archive/delete` |
| 3 | 23:00 | Reminders + Calendar | 31 → 91 | `991cb68 feat(reminders,calendar): past cleanup + duplicate detection` |
| 4 | 23:30 | Contacts + Mail + unified CLI + integration | 38 → 129 | `v1.0.0` |

## License

MIT — see [LICENSE](./LICENSE).

## Acknowledgements

- Schema research from [`terrylica/cc-skills@imessage-query`](https://skills.sh/terrylica/cc-skills/imessage-query)
- Predecessor spike: [`junhey/imessage-spam-cleanup`](https://github.com/junhey/imessage-spam-cleanup)
- Built using [skill-creator](https://skills.sh) agent-skill scaffolding
