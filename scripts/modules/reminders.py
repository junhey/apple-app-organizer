"""
Reminders module.

Data source: Reminders.app via AppleScript.

Safety: Deletion is IRREVERSIBLE — Reminders.app has no trash/recovery.
        We always require --execute and --yes for actual deletion.
"""

import subprocess
import time
import re
from datetime import datetime, timedelta
from typing import Optional

from .utils import write_markdown

# Default keywords suggesting promotional/auto-generated reminders
PROMO_KEYWORDS = ["【", "★", "限时", "秒杀", "优惠", "活动", "抢购"]


def check_permissions() -> bool:
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Reminders" to get name of first list'],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode == 0


def _escape_as(s: str) -> str:
    """Escape double-quotes for AppleScript string interpolation."""
    return s.replace('"', '\\"')


def _run(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Reminders AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def scan(whitelist: Optional[dict] = None, older_than_days: int = 365 * 10) -> list[dict]:
    """
    Return completed or overdue reminders older than older_than_days.
    Reminders are NOT deleted unless explicitly cleaned.
    """
    whitelist = whitelist or {}
    protected_titles = {t.lower() for t in whitelist.get("reminder_titles", [])}

    cutoff = datetime.now() - timedelta(days=older_than_days)
    cutoff_stamp = cutoff.strftime("%Y-%m-%d")

    # Get all reminders
    script = (
        'tell application "Reminders"\n'
        '  set allReminders to every reminder\n'
        '  set resultList to {}\n'
        '  repeat with r in allReminders\n'
        '    set rId to id of r\n'
        '    set rName to name of r\n'
        '    set rCompleted to completed of r\n'
        '    set rDate to completion date of r\n'
        '    set rDue to due date of r\n'
        '    set rBody to body of r\n'
        '    set rListName to name of container of r\n'
        '    copy {id:rId, name:rName, completed:rCompleted, '
        '          completionDate:rDate, dueDate:rDue, '
        '          body:rBody, listName:rListName} to end of resultList\n'
        '  end repeat\n'
        '  return resultList as JSON\n'
        'end tell'
    )
    try:
        import json
        raw = _run(script)
        all_reminders = json.loads(raw)
    except Exception:
        return []

    results = []
    for r in all_reminders:
        reason = None
        completed_dt: Optional[datetime] = None
        if r.get("completionDate") and r["completionDate"] != "missing value":
            try:
                completed_dt = datetime.fromisoformat(r["completionDate"].replace("Z", "+00:00"))
            except Exception:
                pass

        if completed_dt and completed_dt < cutoff:
            reason = f"completed {completed_dt.date()} (>{older_than_days}d ago)"
        elif r.get("dueDate") and r["dueDate"] != "missing value":
            try:
                due_dt = datetime.fromisoformat(r["dueDate"].replace("Z", "+00:00"))
                if due_dt < datetime.now() - timedelta(days=older_than_days):
                    reason = f"overdue since {due_dt.date()} (>{older_than_days}d)"
            except Exception:
                pass

        # Check promo keywords in name
        name_lower = (r.get("name") or "").lower()
        if any(kw in name_lower for kw in PROMO_KEYWORDS):
            reason = reason or "promotional keyword"

        if reason and name_lower not in protected_titles:
            results.append({
                "id": r.get("id", ""),
                "name": r.get("name", "(unnamed)"),
                "list": r.get("listName", "Unknown"),
                "completed": r.get("completed", False),
                "completion_date": completed_dt.isoformat() if completed_dt else "",
                "due_date": r.get("dueDate", ""),
                "reason": reason,
            })
    return results


def clean(items: list[dict], dry_run: bool = True, whitelist: Optional[dict] = None) -> list[dict]:
    """
    Delete reminders. REMINDERS HAS NO TRASH — this is irreversible!
    Only proceeds if --execute is passed.
    """
    deleted = []
    for item in items:
        if dry_run:
            continue
        rem_id = item.get("id", "")
        # Reminder IDs are URLs: x-apple-reminderkit://REMCDID/...
        # AppleScript needs them unquoted for 'reminder id'
        safe_id = rem_id.replace('"', '')
        script = (
            f'tell application "Reminders"\n'
            f'  set r to reminder id "{_escape_as(safe_id)}"\n'
            f'  delete r\n'
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
    older_than_days: int = 365,
) -> "Path":
    from pathlib import Path
    output_dir = output_dir or Path("/tmp/apple-app-organizer")
    items = scan(whitelist=whitelist, older_than_days=older_than_days)
    lines = [
        "# Reminders Cleanup Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        f"**Total flagged reminders:** {len(items)}",
        "",
        "| # | Name | List | Completed | Completion Date | Reason |",
        "|---|------|------|-----------|----------------|--------|",
    ]
    for i, item in enumerate(items, 1):
        lines.append(
            f"| {i} | {item['name'][:50]} | {item['list']} | "
            f"{item['completed']} | {item['completion_date'][:10] if item['completion_date'] else '—'} | "
            f"{item['reason']} |"
        )
    lines.append("")
    lines.append("## ⚠️ Warning")
    lines.append("**Reminders deletion is IRREVERSIBLE.** There is no trash or recovery.")
    lines.append("Use `--execute --yes` only after carefully reviewing this report.")
    path = output_dir / "reminders_report.md"
    write_markdown(lines, path)
    return path


def add_cli_args(parser):
    parser.add_argument("--older-than-days", type=int, default=365,
                        help="Flag reminders completed/overdue for more than N days (default: 365)")
