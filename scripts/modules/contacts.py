"""
Contacts module.

Data source: Contacts.app via AppleScript 'tell application "Contacts"'.

Capabilities:
  - scan_contacts()       — enumerate all contacts with phones/emails/org
  - detect_duplicates_by_phone()  — normalized phone grouping
  - detect_duplicates_by_email() — case-insensitive email grouping
  - merge_duplicates()    — NO scriptable merge in Contacts.app;
                             documented workaround: UI automation or manual
  - export_duplicates_report() → Markdown

Safety: No automatic deletion — only generates merge report for user review.
        Contacts.app has no built-in trash; merged contacts are permanent.
"""

import subprocess
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .utils import normalize_phone, normalize_email, write_markdown


def check_permissions() -> bool:
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Contacts" to get name of first person'],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


def _run(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Contacts AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def _phones_of(person_script_obj: str) -> list[str]:
    """Return list of phone numbers for a person via AS."""
    script = (
        f'tell application "Contacts"\n'
        f'  tell {person_script_obj}\n'
        f'    set phoneList to value of every phone of it\n'
        f'  end tell\n'
        f'  return phoneList as JSON\n'
        f'end tell'
    )
    try:
        return json.loads(_run(script))
    except Exception:
        return []


def _emails_of(person_script_obj: str) -> list[str]:
    script = (
        f'tell application "Contacts"\n'
        f'  tell {person_script_obj}\n'
        f'    set emailList to value of every email of it\n'
        f'  end tell\n'
        f'  return emailList as JSON\n'
        f'end tell'
    )
    try:
        return json.loads(_run(script))
    except Exception:
        return []


def _org_of(person_script_obj: str) -> str:
    script = (
        f'tell application "Contacts"\n'
        f'  tell {person_script_obj}\n'
        f'    return organization of it\n'
        f'  end tell\n'
        f'end tell'
    )
    try:
        return _run(script)
    except Exception:
        return ""


def scan_contacts() -> list[dict]:
    """
    Enumerate all contacts. Returns list of dicts:
      { id, full_name, phones, emails, organization }
    """
    # First get all person names for pagination
    script = (
        'tell application "Contacts"\n'
        '  set allPeople to every person\n'
        '  set nameList to {}\n'
        '  repeat with p in allPeople\n'
        '    copy {name:name of p, id:id of p} to end of nameList\n'
        '  end repeat\n'
        '  return nameList as JSON\n'
        'end tell'
    )
    try:
        people_meta = json.loads(_run(script))
    except Exception:
        return []

    results = []
    for meta in people_meta:
        pid = meta.get("id", "")
        name = meta.get("name", "")
        if not name or name == "missing value":
            name = "(no name)"
        # Get phones, emails, org
        phones = _phones_of(f'person id "{pid}"')
        emails = _emails_of(f'person id "{pid}"')
        org = _org_of(f'person id "{pid}"')
        if org == "missing value":
            org = ""
        results.append({
            "id": pid,
            "full_name": name,
            "phones": phones,
            "emails": emails,
            "organization": org,
        })
    return results


def detect_duplicates_by_phone(contacts: Optional[list[dict]] = None) -> list[dict]:
    """
    Group contacts sharing the same normalized phone number.
    Returns list of groups: { phone_normalized, contacts: [...] }
    """
    if contacts is None:
        contacts = scan_contacts()

    groups: dict[str, list] = {}
    for c in contacts:
        for raw_phone in c.get("phones", []):
            norm = normalize_phone(raw_phone)
            if len(norm) < 7:  # Skip too-short numbers
                continue
            groups.setdefault(norm, []).append(c)

    duplicates = []
    for norm, members in groups.items():
        if len(members) > 1:
            duplicates.append({
                "phone_normalized": norm,
                "phone_raw": members[0]["phones"][0] if members[0]["phones"] else norm,
                "contacts": members,
                "count": len(members),
            })
    return duplicates


def detect_duplicates_by_email(contacts: Optional[list[dict]] = None) -> list[dict]:
    """
    Group contacts sharing the same normalized (case-insensitive) email.
    Returns list of groups: { email_normalized, contacts: [...] }
    """
    if contacts is None:
        contacts = scan_contacts()

    groups: dict[str, list] = {}
    for c in contacts:
        for raw_email in c.get("emails", []):
            norm = normalize_email(raw_email)
            if "@" not in norm:  # Skip malformed
                continue
            groups.setdefault(norm, []).append(c)

    duplicates = []
    for norm, members in groups.items():
        if len(members) > 1:
            duplicates.append({
                "email_normalized": norm,
                "contacts": members,
                "count": len(members),
            })
    return duplicates


def merge_duplicates(
    group: dict,
    dry_run: bool = True,
) -> dict:
    """
    Merge a group of duplicate contacts.

    IMPORTANT: Contacts.app AppleScript does NOT expose a 'merge' verb.
    The canonical workaround is:

    Option A — Manual UI merge (recommended for safety):
      1. Open Contacts.app
      2. Select the primary contact to keep
      3. Cmd+click additional contacts to multi-select
      4. Menu: Card → Merge (合并重复联系人)
         Note: the "Merge" menu item is only available when exactly 2 contacts
         are selected; for 3+ iterate pairwise.

    Option B — UI Automation (programmatic, risky):
      Use System Events to:
        1. Open Contacts.app
        2. Search for contact A → select
        3. Search for contact B → Cmd+click to add to selection
        4. Click Card → Merge
      This requires precise UI element targeting and is fragile across OS versions.

    Option C — Third-party CLI (requires AddressBook framework):
      A shell script using '/usr/bin/defaults' or AddressBook framework
      can programmatically deduplicate, but requires Full Disk Access and
      carries data-loss risk.

    This function documents the intended workflow and returns the plan
    regardless of dry_run setting. No mutation is performed.
    """
    contacts_list = group.get("contacts", [])
    primary = contacts_list[0] if contacts_list else {}

    plan = {
        "strategy": "manual_merge_required",
        "reason": (
            "Contacts.app AppleScript does not expose a 'merge' verb. "
            "Manual merge via UI is required. See Option A above."
        ),
        "keep": primary.get("full_name", ""),
        "keep_id": primary.get("id", ""),
        "merge_ids": [c.get("id", "") for c in contacts_list[1:]],
        "merge_names": [c.get("full_name", "") for c in contacts_list[1:]],
        "dry_run": dry_run,
        "note": "No changes made — review and perform merge manually in Contacts.app",
    }
    return plan


def export_duplicates_report(
    phone_dupes: Optional[list[dict]] = None,
    email_dupes: Optional[list[dict]] = None,
    output_dir: Path = Path("/tmp/apple-app-organizer"),
) -> Path:
    """
    Generate a Markdown merge report for duplicate contacts.
    Includes step-by-step merge instructions.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    contacts = scan_contacts()
    if phone_dupes is None:
        phone_dupes = detect_duplicates_by_phone(contacts)
    if email_dupes is None:
        email_dupes = detect_duplicates_by_email(contacts)

    lines = [
        "# Contacts Duplicate Merge Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        f"**Phone-based duplicates:** {len(phone_dupes)} group(s)",
        f"**Email-based duplicates:** {len(email_dupes)} group(s)",
        "",
    ]

    if phone_dupes:
        lines += [
            "## Phone Number Duplicates",
            "",
            "### How to merge (Contacts.app — Manual)",
            "",
            "1. Open **Contacts** app",
            "2. Select the contact you want to **keep**",
            "3. **Cmd+click** the other duplicate(s) to multi-select",
            "4. Menu: **Card → Merge** (合并重复联系人) — only appears with 2+ selected",
            "   > Note: merge only works on 2 contacts at a time; for 3+, merge pairwise",
            "",
        ]
        for i, group in enumerate(phone_dupes, 1):
            lines.append(f"### Group {i}: `{group['phone_raw']}` ({group['count']} contacts)")
            lines.append("")
            lines.append("| # | Name | Organization | Phones | Emails |")
            lines.append("|---|------|-------------|--------|--------|")
            for j, c in enumerate(group["contacts"], 1):
                lines.append(
                    f"| {j} | {c['full_name']} | {c['organization'] or '—'} | "
                    f"{', '.join(c['phones'])} | {', '.join(c['emails']) or '—'} |"
                )
            lines.append("")

    if email_dupes:
        lines += [
            "## Email Duplicates",
            "",
        ]
        for i, group in enumerate(email_dupes, 1):
            lines.append(f"### Group {i}: `{group['email_normalized']}` ({group['count']} contacts)")
            lines.append("")
            lines.append("| # | Name | Organization | Phones | Emails |")
            lines.append("|---|------|-------------|--------|--------|")
            for j, c in enumerate(group["contacts"], 1):
                lines.append(
                    f"| {j} | {c['full_name']} | {c['organization'] or '—'} | "
                    f"{', '.join(c['phones']) or '—'} | {', '.join(c['emails'])} |"
                )
            lines.append("")

    if not phone_dupes and not email_dupes:
        lines.append("**No duplicate contacts found.** 🎉")

    lines += [
        "",
        "## ⚠️ Important Notes",
        "",
        "- **No automatic merge** — Contacts.app has no scriptable merge verb.",
        "  You must perform merges manually in the Contacts.app UI.",
        "- **Contacts.app has no trash** — merged contacts are permanent.",
        "- **Backup** before merging: File → Export → vCard… for each contact group.",
    ]

    path = output_dir / "contacts_report.md"
    write_markdown(lines, path)
    return path


# ── Module interface (matches other modules) ─────────────────────────────────

def scan(whitelist: Optional[dict] = None) -> list[dict]:
    """Alias for scan_contacts()."""
    return scan_contacts()


def generate_report(
    whitelist: Optional[dict] = None,
    output_dir: Path = Path("/tmp/apple-app-organizer"),
) -> Path:
    return export_duplicates_report(output_dir=output_dir)


def clean(
    items: list[dict],
    dry_run: bool = True,
    whitelist: Optional[dict] = None,
) -> list[dict]:
    """
    For contacts, clean() returns merge plans. No actual mutation occurs.
    Contacts.app does not support programmatic merge.
    """
    plans = [merge_duplicates(item, dry_run=dry_run) for item in items]
    return plans


def add_cli_args(parser):
    parser.add_argument("--by-phone", action="store_true",
                        help="Detect duplicates by phone number (default)")
    parser.add_argument("--by-email", action="store_true",
                        help="Detect duplicates by email address")
    parser.add_argument("--export-report", action="store_true",
                        help="Export full merge report to Markdown")
