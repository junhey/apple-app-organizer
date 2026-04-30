#!/usr/bin/env python3
"""apple-app-organizer unified CLI.

Usage:
    organize.py <module> <action> [flags]

Modules: messages | notes | reminders | calendar | contacts | mail
Actions: scan | report | clean | status

Every mutating action defaults to --dry-run. Pass --execute to actually mutate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make sibling 'modules' importable whether run directly or installed
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from modules import common  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans == "y"


def _print_summary_table(title: str, rows: list[dict], columns: list[str]) -> None:
    print(f"\n=== {title} ({len(rows)}) ===")
    if not rows:
        print("  (empty)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    print(header)
    print("-" * len(header))
    for r in rows[:50]:
        print("  ".join(str(r.get(c, ""))[: widths[c]].ljust(widths[c]) for c in columns))
    if len(rows) > 50:
        print(f"  ... ({len(rows) - 50} more rows)")


# --------------------------------------------------------------------------- #
# Module handlers
# --------------------------------------------------------------------------- #

def cmd_messages(args: argparse.Namespace) -> int:
    from modules import messages

    if args.action == "scan":
        result = messages.scan()
        _print_summary_table(
            "Spam", result["spam"], ["chat_id", "msg_count", "reason"]
        )
        _print_summary_table(
            "Normal", result["normal"], ["chat_id", "msg_count", "reason"]
        )
        _print_summary_table(
            "Unknown", result["unknown"], ["chat_id", "msg_count", "reason"]
        )
        return 0

    if args.action == "report":
        result = messages.scan()
        json_path = common.write_json_report(result, args.output_dir, prefix="messages")
        md_path = common.write_markdown_report(
            "Messages Cleanup Report",
            [
                ("Spam", result["spam"], ["chat_id", "msg_count", "reason", "last_text"]),
                ("Unknown", result["unknown"], ["chat_id", "msg_count", "reason", "last_text"]),
                ("Normal (protected)", result["normal"], ["chat_id", "msg_count", "reason"]),
            ],
            args.output_dir, prefix="messages",
        )
        print(f"JSON  -> {json_path}")
        print(f"Markd -> {md_path}")
        return 0

    if args.action == "clean":
        result = messages.scan()
        targets = {e["chat_id"] for e in result["spam"]}
        print(f"Targets: {len(targets)} spam chats")
        dry = not args.execute
        if not dry and not _confirm(
            f"Really delete {len(targets)} conversations?", args.yes
        ):
            print("Aborted.")
            return 1
        res = messages.batch_delete(targets, dry_run=dry)
        print(f"{'[DRY] ' if dry else ''}Deleted: {len(res.deleted)}")
        print(f"Skipped protected: {len(res.skipped_protected)}")
        if res.halted_on:
            print(f"Halted on: {res.halted_on} ({res.error})")
        return 0

    print(f"Unknown action '{args.action}' for messages")
    return 2


def cmd_notes(args: argparse.Namespace) -> int:
    from modules import notes

    if args.action == "scan":
        rows = notes.scan_notes()
        _print_summary_table("All Notes", rows,
                              ["uuid", "title", "folder", "modified"])
        return 0

    if args.action == "report":
        rows = notes.scan_notes()
        dups = notes.detect_duplicates(rows)
        empties = notes.detect_empty(rows, min_chars=args.min_chars)
        dup_rows = [{"group": f"#{i}", "uuid": n["uuid"], "title": n["title"],
                     "folder": n["folder"]}
                    for i, g in enumerate(dups, 1) for n in g]
        empty_rows = [n for n in rows if n["uuid"] in set(empties)]
        json_path = common.write_json_report(
            {"notes": rows, "duplicates": dups, "empty": empty_rows},
            args.output_dir, prefix="notes",
        )
        md_path = common.write_markdown_report(
            "Notes Cleanup Report",
            [
                (f"Duplicate Groups ({len(dups)})", dup_rows,
                 ["group", "uuid", "title", "folder"]),
                (f"Empty / Short Notes ({len(empty_rows)})", empty_rows,
                 ["uuid", "title", "folder", "modified"]),
            ],
            args.output_dir, prefix="notes",
        )
        print(f"JSON  -> {json_path}")
        print(f"Markd -> {md_path}")
        return 0

    print(f"Action '{args.action}' for notes is not yet implemented for clean — use report then archive manually")
    return 2


def cmd_reminders(args: argparse.Namespace) -> int:
    from modules import reminders

    if args.action == "scan":
        lists = reminders.list_lists()
        _print_summary_table("Lists", lists,
                             ["name", "total", "completed", "overdue"])
        return 0

    if args.action == "report":
        completed = reminders.list_completed(older_than_days=args.older_than_days)
        overdue = reminders.list_overdue()
        json_path = common.write_json_report(
            {"completed": completed, "overdue": overdue},
            args.output_dir, prefix="reminders",
        )
        md_path = common.write_markdown_report(
            "Reminders Cleanup Report",
            [
                (f"Completed > {args.older_than_days}d",
                 completed, ["id", "name", "completion_date", "list"]),
                ("Overdue (still open)", overdue,
                 ["id", "name", "due_date", "list"]),
            ],
            args.output_dir, prefix="reminders",
        )
        print(f"JSON  -> {json_path}")
        print(f"Markd -> {md_path}")
        return 0

    if args.action == "clean":
        dry = not args.execute
        res = reminders.batch_delete_completed(
            older_than_days=args.older_than_days,
            dry_run=dry,
        )
        print(f"{'[DRY] ' if dry else ''}Targeted: {len(res.targeted)}")
        print(f"Deleted: {len(res.deleted)}")
        print(f"Failed:  {len(res.failed)}")
        return 0

    return 2


def cmd_calendar(args: argparse.Namespace) -> int:
    from modules import calendar as cal_module

    if args.action == "scan":
        cals = cal_module.list_calendars()
        _print_summary_table("Calendars", cals,
                             ["name", "event_count", "color"])
        return 0

    if args.action == "report":
        events = cal_module.list_past_events(
            older_than_months=args.older_than_months,
            exclude_calendars=args.exclude or (),
        )
        dups = cal_module.detect_recurring_duplicates(events)
        dup_rows = [{"group": f"#{i}", "id": e["id"], "summary": e["summary"],
                     "start_date": e["start_date"], "calendar": e["calendar"]}
                    for i, g in enumerate(dups, 1) for e in g]
        json_path = common.write_json_report(
            {"past_events": events, "duplicate_groups": dups},
            args.output_dir, prefix="calendar",
        )
        md_path = common.write_markdown_report(
            "Calendar Cleanup Report",
            [
                (f"Past events > {args.older_than_months}mo ({len(events)})",
                 events, ["id", "summary", "start_date", "calendar"]),
                (f"Duplicate recurring events ({len(dups)} groups)",
                 dup_rows, ["group", "summary", "start_date", "calendar"]),
            ],
            args.output_dir, prefix="calendar",
        )
        print(f"JSON  -> {json_path}")
        print(f"Markd -> {md_path}")
        return 0

    if args.action == "clean":
        dry = not args.execute
        res = cal_module.purge_past(
            older_than_months=args.older_than_months,
            whitelist_calendars=args.exclude or (),
            dry_run=dry,
        )
        print(f"{'[DRY] ' if dry else ''}Targeted: {len(res.targeted)}")
        print(f"Deleted: {len(res.deleted)}")
        print(f"Failed:  {len(res.failed)}")
        return 0

    return 2


def cmd_contacts(args: argparse.Namespace) -> int:
    from modules import contacts

    if args.action in ("scan", "report"):
        ppl = contacts.scan_contacts()
        if args.action == "scan":
            _print_summary_table("Contacts", ppl,
                                 ["id", "full_name", "organization"])
            return 0
        path = contacts.export_duplicates_report(ppl, out_dir=args.output_dir)
        print(f"Markd -> {path}")
        return 0

    if args.action == "clean":
        print("Contacts.app has no scriptable merge. Use report action, then "
              "merge manually via Contacts → Card → Look for Duplicates.")
        return 1
    return 2


def cmd_mail(args: argparse.Namespace) -> int:
    from modules import mail

    if args.action == "scan":
        mbs = mail.scan_mailboxes()
        _print_summary_table("Mailboxes", mbs,
                             ["name", "account", "total", "unread"])
        return 0

    if args.action == "report":
        if not args.mailbox or not args.account:
            print("--mailbox and --account are required for mail report")
            return 2
        ads = mail.classify_ads(args.mailbox, args.account)
        old = mail.detect_old_unread(older_than_months=args.older_than_months)
        json_path = common.write_json_report(
            {"ads": ads, "old_unread": old}, args.output_dir, prefix="mail",
        )
        md_path = common.write_markdown_report(
            "Mail Cleanup Report",
            [
                (f"Ad candidates in {args.mailbox}", ads,
                 ["id", "subject", "sender", "date"]),
                (f"Old unread > {args.older_than_months}mo", old,
                 ["id", "subject", "sender", "account", "mailbox"]),
            ],
            args.output_dir, prefix="mail",
        )
        print(f"JSON  -> {json_path}")
        print(f"Markd -> {md_path}")
        return 0

    if args.action == "clean":
        if not args.mailbox or not args.account:
            print("--mailbox and --account are required for mail clean")
            return 2
        dry = not args.execute
        ads = mail.classify_ads(args.mailbox, args.account)
        res = mail.move_to_trash(
            [a["id"] for a in ads],
            account=args.account,
            source_mailbox=args.mailbox,
            dry_run=dry,
        )
        print(f"{'[DRY] ' if dry else ''}Trashed: {len(res.trashed)}")
        print(f"Failed:  {len(res.failed)}")
        return 0

    return 2


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="organize",
        description="apple-app-organizer — macOS built-in app cleanup suite",
    )
    p.add_argument("--output-dir", type=Path,
                   default=common.DEFAULT_OUTPUT_DIR,
                   help="where reports are written")
    p.add_argument("--execute", action="store_true",
                   help="actually mutate (default is dry-run)")
    p.add_argument("--yes", action="store_true",
                   help="skip interactive confirmations")

    sub = p.add_subparsers(dest="module", required=True)

    # messages
    s = sub.add_parser("messages", help="iMessage / SMS cleanup")
    s.add_argument("action", choices=["scan", "report", "clean"])

    # notes
    s = sub.add_parser("notes", help="Notes.app cleanup")
    s.add_argument("action", choices=["scan", "report"])
    s.add_argument("--min-chars", type=int, default=10,
                   help="notes shorter than this are 'empty' (default 10)")

    # reminders
    s = sub.add_parser("reminders", help="Reminders.app cleanup")
    s.add_argument("action", choices=["scan", "report", "clean"])
    s.add_argument("--older-than-days", type=int, default=30)

    # calendar
    s = sub.add_parser("calendar", help="Calendar.app cleanup")
    s.add_argument("action", choices=["scan", "report", "clean"])
    s.add_argument("--older-than-months", type=int, default=12)
    s.add_argument("--exclude", nargs="*",
                   help="calendars to protect (space-separated)")

    # contacts
    s = sub.add_parser("contacts", help="Contacts.app cleanup")
    s.add_argument("action", choices=["scan", "report", "clean"])

    # mail
    s = sub.add_parser("mail", help="Mail.app cleanup")
    s.add_argument("action", choices=["scan", "report", "clean"])
    s.add_argument("--mailbox")
    s.add_argument("--account")
    s.add_argument("--older-than-months", type=int, default=12)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "messages": cmd_messages,
        "notes": cmd_notes,
        "reminders": cmd_reminders,
        "calendar": cmd_calendar,
        "contacts": cmd_contacts,
        "mail": cmd_mail,
    }
    handler = handlers[args.module]
    try:
        return handler(args)
    except common.AppleScriptError as e:
        print(f"AppleScript error: {e}", file=sys.stderr)
        return 3
    except FileNotFoundError as e:
        print(f"Missing file: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
