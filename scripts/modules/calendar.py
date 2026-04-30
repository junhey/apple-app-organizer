"""Calendar (Calendar.app) cleanup module.

Public API:
- list_calendars()                             -> [{"name", "color", "event_count"}]
- list_past_events(older_than_months, exclude) -> [{"id", "summary", "start_date", "calendar"}]
- delete_event(event_uid, calendar_name, dry_run=True) -> bool
- detect_recurring_duplicates()                -> list of event groups with identical summary+date
- purge_past(older_than_months, whitelist, dry_run=True) -> PurgeResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import common


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _parse_lines(stdout: str, field_count: int) -> list[list[str]]:
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

def list_calendars() -> list[dict]:
    """Return each calendar with name, color, and event count."""
    script = """
    tell application "Calendar"
        set output to ""
        repeat with cal in calendars
            try
                set c to count of events of cal
                set col to ""
                try
                    set col to color of cal as string
                end try
                set output to output & (name of cal as string) & tab & col & tab & c & linefeed
            end try
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=60)
    result = []
    for row in _parse_lines(stdout, 3):
        name, color, count = row
        result.append({
            "name": name,
            "color": color,
            "event_count": int(count),
        })
    return result


def list_past_events(
    older_than_months: int = 6,
    exclude_calendars: Iterable[str] = (),
    limit_per_calendar: int = 500,
) -> list[dict]:
    """Enumerate events that started before (now - N months)."""
    exclude = set(exclude_calendars)
    days = older_than_months * 30
    script = f"""
    tell application "Calendar"
        set cutoff to (current date) - ({days} * days)
        set output to ""
        repeat with cal in calendars
            try
                set calName to name of cal as string
                set evCount to 0
                repeat with e in (events of cal whose start date < cutoff)
                    try
                        set output to output & (uid of e as string) & tab & ¬
                            (summary of e as string) & tab & ¬
                            (start date of e as string) & tab & ¬
                            calName & linefeed
                        set evCount to evCount + 1
                        if evCount >= {limit_per_calendar} then exit repeat
                    end try
                end repeat
            end try
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=120)
    result = []
    for row in _parse_lines(stdout, 4):
        uid, summary, start_date, cal_name = row
        if cal_name in exclude:
            continue
        result.append({
            "id": uid,
            "summary": summary,
            "start_date": start_date,
            "calendar": cal_name,
        })
    return result


def delete_event(event_uid: str, calendar_name: str, *, dry_run: bool = True) -> bool:
    """Delete event by uid within a specific calendar."""
    if not event_uid or not calendar_name:
        return False
    if dry_run:
        return True
    # Escape quotes
    cal_escaped = calendar_name.replace('"', '\\"')
    uid_escaped = event_uid.replace('"', '\\"')
    script = f"""
    tell application "Calendar"
        try
            tell calendar "{cal_escaped}"
                delete (first event whose uid is "{uid_escaped}")
            end tell
            return "OK"
        on error errMsg
            return "ERR:" & errMsg
        end try
    end tell
    """
    result = common.osa(script, timeout=15)
    return result == "OK"


def detect_recurring_duplicates(events: list[dict] | None = None) -> list[list[dict]]:
    """Group events that share identical summary+start_date (duplicate recurring siblings).

    If no events list is given, scan last 12 months of all calendars.
    """
    if events is None:
        events = list_past_events(older_than_months=12)
    buckets: dict[tuple[str, str], list[dict]] = {}
    for e in events:
        key = (e.get("summary", ""), e.get("start_date", ""))
        buckets.setdefault(key, []).append(e)
    return [group for group in buckets.values() if len(group) > 1]


@dataclass
class PurgeResult:
    targeted: list[dict] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped_whitelist: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = True


def purge_past(
    older_than_months: int = 12,
    whitelist_calendars: Iterable[str] = (),
    *,
    dry_run: bool = True,
    on_progress: Callable[[dict], None] | None = None,
) -> PurgeResult:
    """Delete past events older than N months, skipping whitelisted calendars."""
    whitelist = set(whitelist_calendars)
    events = list_past_events(
        older_than_months=older_than_months,
        exclude_calendars=whitelist,
    )
    result = PurgeResult(
        targeted=events,
        dry_run=dry_run,
    )
    total = len(events)
    for i, e in enumerate(events, 1):
        if e["calendar"] in whitelist:
            result.skipped_whitelist.append(e["id"])
            continue
        if on_progress:
            on_progress({"index": i, "total": total, "current": e})
        ok = delete_event(e["id"], e["calendar"], dry_run=dry_run)
        if ok:
            result.deleted.append(e["id"])
        else:
            result.failed.append((e["id"], "delete_failed"))
    return result
