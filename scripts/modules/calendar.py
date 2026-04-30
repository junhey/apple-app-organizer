"""
Calendar module.

Data source: Calendar.app via AppleScript.

Safety: Calendar event deletion is IRREVERSIBLE — no trash/recovery.
        All-day events stored in UTC; AppleScript may return TZ-shifted dates.
        Recurring events: detached instances create new uid; group by (summary, hour).
"""

import subprocess
import time
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .utils import write_markdown

DEFAULT_OLDER_THAN_MONTHS = 12


def check_permissions() -> bool:
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Calendar" to get name of first calendar'],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode == 0


def _run(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Calendar AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def _parse_as_date(raw: str) -> Optional[datetime]:
    if not raw or raw == "missing value":
        return None
    try:
        # AppleScript returns "date \"YYYY-MM-DD HH:MM:SS\""
        raw = re.sub(r'^date\s+"', "", raw.replace('"', ""))
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _all_day_date(raw: str) -> Optional[str]:
    """Extract date string from allDay event."""
    if not raw or raw == "missing value":
        return None
    try:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
        return m.group(1) if m else None
    except Exception:
        return None


def _is_all_day(script: str) -> str:
    """Return 'true' or 'false' via JXA."""
    jxa = (
        f'ObjC.unwrap($.NSHomeDirectory());\n'
        f'Application("Calendar").events.byId("{script}")'
    )
    return "false"  # simplified


def scan(
    whitelist: Optional[dict] = None,
    older_than_months: int = DEFAULT_OLDER_THAN_MONTHS,
    calendar_whitelist: Optional[list[str]] = None,
) -> list[dict]:
    """
    Find past calendar events older than older_than_months.
    calendar_whitelist: list of calendar names to protect (e.g. ["Birthdays","Holidays"])
    """
    whitelist = whitelist or {}
    protected_calendars = set(c.lower() for c in (calendar_whitelist or whitelist.get("calendar_names", [])))
    protected_ids = set(whitelist.get("calendar_ids", []))

    cutoff = datetime.now() - timedelta(days=older_than_months * 30)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # Get calendars
    script = (
        'tell application "Calendar"\n'
        '  set calList to every calendar\n'
        '  set result to {}\n'
        '  repeat with cal in calList\n'
        '    copy {id:id of cal, name:name of cal} to end of result\n'
        '  end repeat\n'
        '  return result as JSON\n'
        'end tell'
    )
    try:
        raw = _run(script)
        calendars = json.loads(raw)
    except Exception:
        calendars = []

    cal_id_to_name = {c["id"]: c["name"] for c in calendars}
    results = []

    for cal_id, cal_name in cal_id_to_name.items():
        if cal_name.lower() in protected_calendars:
            continue
        # Get events for this calendar
        script2 = (
            f'tell application "Calendar"\n'
            f'  set evList to events of calendar id "{cal_id}"\n'
            f'  whose start date < date "{cutoff_str}"\n'
            f'  set resultList to {{}}\n'
            f'  repeat with ev in evList\n'
            f'    set evId to uid of ev\n'
            f'    set evSummary to summary of ev\n'
            f'    set evStart to start date of ev\n'
            f'    set evEnd to end date of ev\n'
            f'    set evAllday to allday event of ev\n'
            f'    copy {{id:evId, summary:evSummary, startDate:evStart, '
            f'          endDate:evEnd, allday:evAllday}} to end of resultList\n'
            f'  end repeat\n'
            f'  return resultList as JSON\n'
            f'end tell'
        )
        try:
            raw2 = _run(script2)
            events = json.loads(raw2)
        except Exception:
            continue

        for ev in events:
            ev_id = ev.get("id", "")
            if ev_id in protected_ids:
                continue
            results.append({
                "id": ev_id,
                "calendar_id": cal_id,
                "calendar_name": cal_name,
                "summary": ev.get("summary", "(no title)"),
                "start_date": ev.get("startDate", ""),
                "reason": f"past event ({older_than_months}+ months ago)",
            })

    return results


def detect_recurring_duplicates(
    whitelist: Optional[dict] = None,
) -> list[dict]:
    """
    Group events with identical summary + hour of day.
    Useful for surfacing detached recurring instances that appear as orphans.
    """
    whitelist = whitelist or {}
    protected_calendars = {c.lower() for c in whitelist.get("calendar_names", [])}

    script = (
        'tell application "Calendar"\n'
        '  set allEvents to every event\n'
        '  set resultList to {}\n'
        '  repeat with ev in allEvents\n'
        '    set evId to uid of ev\n'
        '    set evSummary to summary of ev\n'
        '    set evStart to start date of ev\n'
        '    set evCalName to name of calendar of ev\n'
        '    copy {id:evId, summary:evSummary, startDate:evStart, '
        '          calName:evCalName} to end of resultList\n'
        '  end repeat\n'
        '  return resultList as JSON\n'
        'end tell'
    )
    try:
        raw = _run(script)
        all_events = json.loads(raw)
    except Exception:
        return []

    # Group by (summary_lower, hour_of_day)
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    for ev in all_events:
        summary = (ev.get("summary") or "").strip().lower()
        start_raw = ev.get("startDate", "")
        dt = _parse_as_date(start_raw)
        hour = dt.hour if dt else -1
        key = (summary, hour)
        groups[key].append(ev)

    duplicates = []
    for (summary, hour), events in groups.items():
        if len(events) <= 1:
            continue
        # Filter protected calendars
        protected = [e for e in events if e.get("calName", "").lower() in protected_calendars]
        if len(events) - len(protected) <= 1:
            continue
        duplicates.append({
            "summary": summary,
            "hour": hour,
            "count": len(events),
            "events": events,
        })
    return duplicates


def clean(items: list[dict], dry_run: bool = True, whitelist: Optional[dict] = None) -> list[dict]:
    """
    Delete past calendar events. CALENDAR DELETION IS IRREVERSIBLE.
    Only proceeds if --execute is passed.
    """
    deleted = []
    for item in items:
        if dry_run:
            deleted.append(item)
            continue
        ev_id = item.get("id", "")
        script = (
            f'tell application "Calendar"\n'
            f'  set ev to event id "{ev_id}"\n'
            f'  delete ev\n'
            f'end tell'
        )
        try:
            _run(script)
            deleted.append(item)
        except Exception:
            pass
        time.sleep(0.1)
    return deleted


def generate_report(
    whitelist: Optional[dict] = None,
    output_dir=None,
    older_than_months: int = DEFAULT_OLDER_THAN_MONTHS,
) -> Path:
    output_dir = output_dir or Path("/tmp/apple-app-organizer")
    items = scan(whitelist=whitelist, older_than_months=older_than_months)
    dupes = detect_recurring_duplicates(whitelist=whitelist)

    lines = [
        "# Calendar Cleanup Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        f"**Total past events flagged:** {len(items)}",
        f"**Recurring duplicate series:** {len(dupes)}",
        "",
        "## Past Events",
        "",
        "| # | Summary | Calendar | Start Date |",
        "|---|---------|---------|-------------|",
    ]
    for i, item in enumerate(items[:100], 1):
        lines.append(
            f"| {i} | {item['summary'][:50]} | {item['calendar_name']} | "
            f"{_all_day_date(item.get('start_date','')) or item.get('start_date','')[:10]} |"
        )
    lines.append("")
    lines.append("## Recurring Duplicate Series")
    for d in dupes[:20]:
        lines.append(f"- **{d['summary']}** at hour {d['hour']}:00 → {d['count']} events")
    lines.append("")
    lines.append("## ⚠️ Warning")
    lines.append("**Calendar event deletion is IRREVERSIBLE.** There is no trash.")
    lines.append("Use `--execute --yes` only after carefully reviewing this report.")
    path = output_dir / "calendar_report.md"
    write_markdown(lines, path)
    return path


def add_cli_args(parser):
    parser.add_argument("--older-than-months", type=int, default=DEFAULT_OLDER_THAN_MONTHS,
                        help="Flag events older than N months (default: 12)")
    parser.add_argument("--calendar-whitelist", type=str, default="",
                        help="Comma-separated calendar names to protect (e.g. Birthdays,Holidays)")
