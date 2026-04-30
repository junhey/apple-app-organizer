"""Reminders (Reminders.app) cleanup module.

Public API:
- list_lists()                            -> [{"name", "total", "completed", "overdue"}]
- list_completed(older_than_days=30)      -> [{"id", "name", "completion_date", "list"}]
- list_overdue()                          -> [{"id", "name", "due_date", "list"}]
- delete_reminder(reminder_id, dry_run=True)  -> bool
- batch_delete_completed(older_than_days=30, dry_run=True, on_progress=None) -> BatchResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable

from . import common


# --------------------------------------------------------------------------- #
# AppleScript helpers
# --------------------------------------------------------------------------- #

def _parse_applescript_date(text: str) -> datetime | None:
    """Parse AppleScript date string into a naive datetime.

    AppleScript dates come back locale-formatted, e.g.
        'Saturday, March 7, 2026 at 10:30:00 AM'
        '2026年3月7日 星期六 上午10:30:00'
    Return None on parse failure (caller treats as unknown).
    """
    if not text:
        return None
    text = text.strip().replace(" at ", " ")
    for fmt in (
        "%A, %B %d, %Y %I:%M:%S %p",
        "%A, %B %d, %Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_lines(stdout: str, field_count: int) -> list[list[str]]:
    """Split tab-separated AppleScript output into rows."""
    rows = []
    for line in stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= field_count:
            rows.append(parts[:field_count])
    return rows


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def list_lists() -> list[dict]:
    """Enumerate Reminders lists with counts."""
    script = """
    tell application "Reminders"
        set output to ""
        repeat with lst in lists
            set total to count of reminders of lst
            set comp to count of (reminders of lst whose completed is true)
            set over to 0
            try
                set nowD to current date
                set over to count of (reminders of lst whose completed is false and due date is not missing value and due date < nowD)
            end try
            set output to output & (name of lst as string) & tab & total & tab & comp & tab & over & linefeed
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=30)
    result = []
    for row in _parse_lines(stdout, 4):
        name, total, completed, overdue = row
        result.append({
            "name": name,
            "total": int(total),
            "completed": int(completed),
            "overdue": int(overdue),
        })
    return result


def list_completed(older_than_days: int = 30) -> list[dict]:
    """Return completed reminders whose completion_date is older than N days."""
    cutoff_secs = older_than_days * 86400
    script = f"""
    tell application "Reminders"
        set cutoff to (current date) - {cutoff_secs}
        set output to ""
        repeat with lst in lists
            repeat with r in (reminders of lst whose completed is true)
                try
                    set compDate to completion date of r
                    if compDate is not missing value and compDate < cutoff then
                        set output to output & (id of r as string) & tab & ¬
                            (name of r as string) & tab & ¬
                            (compDate as string) & tab & ¬
                            (name of lst as string) & linefeed
                    end if
                end try
            end repeat
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=60)
    result = []
    for row in _parse_lines(stdout, 4):
        rid, name, comp_date, list_name = row
        result.append({
            "id": rid,
            "name": name,
            "completion_date": comp_date,
            "list": list_name,
        })
    return result


def list_overdue() -> list[dict]:
    """Return open (non-completed) reminders whose due_date is in the past."""
    script = """
    tell application "Reminders"
        set nowD to current date
        set output to ""
        repeat with lst in lists
            repeat with r in (reminders of lst whose completed is false)
                try
                    set dueD to due date of r
                    if dueD is not missing value and dueD < nowD then
                        set output to output & (id of r as string) & tab & ¬
                            (name of r as string) & tab & ¬
                            (dueD as string) & tab & ¬
                            (name of lst as string) & linefeed
                    end if
                end try
            end repeat
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=60)
    result = []
    for row in _parse_lines(stdout, 4):
        rid, name, due_date, list_name = row
        result.append({
            "id": rid,
            "name": name,
            "due_date": due_date,
            "list": list_name,
        })
    return result


def delete_reminder(reminder_id: str, *, dry_run: bool = True) -> bool:
    """Delete a reminder by id. Returns True on success (or dry-run)."""
    if not reminder_id:
        return False
    if dry_run:
        return True
    # AppleScript's reminder-by-id lookup requires iterating lists
    script = f"""
    tell application "Reminders"
        try
            set target to first reminder whose id is "{reminder_id}"
            delete target
            return "OK"
        on error errMsg
            return "ERR:" & errMsg
        end try
    end tell
    """
    result = common.osa(script, timeout=15)
    return result == "OK"


@dataclass
class BatchResult:
    targeted: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = True


def batch_delete_completed(
    older_than_days: int = 30,
    *,
    dry_run: bool = True,
    on_progress: Callable[[dict], None] | None = None,
) -> BatchResult:
    """Enumerate eligible completed reminders and delete them one by one.

    dry_run=True (default) reports what *would* be deleted.
    """
    eligible = list_completed(older_than_days=older_than_days)
    result = BatchResult(
        targeted=[r["id"] for r in eligible],
        dry_run=dry_run,
    )

    total = len(eligible)
    for i, reminder in enumerate(eligible, 1):
        if on_progress:
            on_progress({
                "index": i,
                "total": total,
                "current": reminder,
            })
        ok = delete_reminder(reminder["id"], dry_run=dry_run)
        if ok:
            result.deleted.append(reminder["id"])
        else:
            result.failed.append((reminder["id"], "delete_failed"))

    return result
