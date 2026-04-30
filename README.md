# apple-app-organizer

[![tests](https://img.shields.io/badge/tests-34%20passing-brightgreen)](./tests)
[![license](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![skill](https://img.shields.io/badge/agent-skill-purple)](https://skills.sh)

A TDD-built, safety-first cleanup suite for macOS's built-in applications.

> **Status: v0.2 Iteration #1 complete** — Messages module migrated, 34 tests green.
> Subsequent iterations (Notes, Reminders, Calendar, Contacts, Mail) scheduled
> every 30 minutes via automation; see [Roadmap](#roadmap).

## What it does

| App | Operations | Safety net |
|-----|-----------|-----------|
| **Messages** | Classify spam / real / unknown → batch delete | Recently Deleted (30d) |
| **Notes** | Detect duplicate / empty notes → archive or delete | "Archive" folder |
| **Reminders** | List overdue / completed → bulk delete | Per-item confirm |
| **Calendar** | Purge past events → detect recurring duplicates | Whitelist calendars |
| **Contacts** | Detect duplicates by phone/email → merge report | Never auto-merges |
| **Mail** | Classify ad mail → move to Trash | Trash, not delete |

## Install

```bash
# Via skills CLI
npx skills add junhey/apple-app-organizer

# Or clone
git clone https://github.com/junhey/apple-app-organizer ~/.workbuddy/skills/apple-app-organizer
```

## Prerequisites

1. **Full Disk Access** — Terminal.app + agent runtime (Cursor, WorkBuddy, Claude Code, Warp, …)
2. **Accessibility** — same runtime
3. **Automation permission** — granted per-app on first prompt

See `references/permissions_guide.md` for a step-by-step walkthrough.

## Quickstart

```bash
# Run the TDD test suite
cd ~/.workbuddy/skills/apple-app-organizer
python3 -m pytest tests/ -v

# Messages — scan and report
python3 scripts/organize.py messages scan
python3 scripts/organize.py messages report

# Messages — dry-run clean
python3 scripts/organize.py messages clean --dry-run

# Messages — execute
python3 scripts/organize.py messages clean --execute --yes
```

## Safety principles

1. **Dry-run by default** — every mutating subcommand requires `--execute`
2. **Whitelist first** — real phone numbers and bank short codes are never deleted
3. **Trash, not delete** — Mail→Trash, Messages→Recently Deleted, Notes→Archive
4. **Loop detection** — UI automation halts after 5 identical window titles
5. **Report first** — every module can emit a Markdown report for user review

## TDD & testing

```bash
python3 -m venv venv && source venv/bin/activate
pip install pytest
pytest tests/ -v --tb=short
```

Test strategy:
- `test_common.py` — pure unit tests for whitelist, normalization, report writers
- `test_messages.py` — unit tests via a fake `chat.db` fixture; UI automation is mocked
- `test_notes.py`, `test_reminders.py` … — analogous, mocked sqlite + mocked osascript
- `test_integration.py` — subprocess end-to-end CLI, always in `--dry-run`

## Roadmap

- [x] **v0.2 #1** (22:00) — Skeleton + Messages module + 34 tests
- [ ] **v0.2 #2** (22:30) — Notes module (scheduled)
- [ ] **v0.2 #3** (23:00) — Reminders + Calendar (scheduled)
- [ ] **v0.2 #4** (23:30) — Contacts + Mail + unified CLI (scheduled)
- [ ] **v1.0.0** (00:00) — Release with full 6-module suite

## License

MIT — see [LICENSE](./LICENSE).

## Acknowledgements

- Schema research from `terrylica/cc-skills@imessage-query`
- Predecessor spike: `junhey/imessage-spam-cleanup`
