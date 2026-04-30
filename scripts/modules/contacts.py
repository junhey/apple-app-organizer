"""Contacts (Contacts.app) cleanup module.

Public API:
- scan_contacts()                 -> [{"id","full_name","phones","emails","organization"}]
- detect_duplicates_by_phone()    -> [[contact, contact, ...]]
- detect_duplicates_by_email()    -> [[contact, contact, ...]]
- export_duplicates_report(...)   -> Path (Markdown)

Note: Contacts.app has no scriptable 'merge' verb, so merging happens via the
report + manual UI action (Card → Look for Duplicates).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from . import common


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_PHONE_CLEAN_RE = re.compile(r"[^\d+]")


def _normalize_phone(phone: str) -> str:
    """Aggressive normalize: digits + leading '+' only, strip '+86' for CN."""
    if not phone:
        return ""
    cleaned = _PHONE_CLEAN_RE.sub("", phone)
    # Strip Chinese country code for local matching
    if cleaned.startswith("+86") and len(cleaned) == 14:
        cleaned = cleaned[3:]
    elif cleaned.startswith("+1") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    return cleaned


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #

def scan_contacts() -> list[dict]:
    """Enumerate all Contacts with phones, emails, organization."""
    # Use ASCII US (0x1F) as inter-field separator; commas appear in phone lists
    script = r"""
    tell application "Contacts"
        set output to ""
        set US to ASCII character 31      -- field separator within a row
        set RS to ASCII character 30      -- row separator
        repeat with p in people
            set phoneList to ""
            try
                repeat with ph in phones of p
                    set phoneList to phoneList & (value of ph as string) & ","
                end repeat
            end try
            set emailList to ""
            try
                repeat with em in emails of p
                    set emailList to emailList & (value of em as string) & ","
                end repeat
            end try
            set orgText to ""
            try
                set orgText to organization of p as string
            end try
            set nameText to ""
            try
                set nameText to name of p as string
            end try
            set output to output & (id of p as string) & US & nameText & US & phoneList & US & emailList & US & orgText & RS
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=120)
    contacts = []
    RS = "\x1e"
    US = "\x1f"
    for row in stdout.split(RS):
        if not row.strip():
            continue
        parts = row.split(US)
        if len(parts) < 5:
            continue
        cid, name, phones, emails, org = parts[:5]
        contacts.append({
            "id": cid,
            "full_name": name.strip(),
            "phones": [p.strip() for p in phones.split(",") if p.strip()],
            "emails": [e.strip() for e in emails.split(",") if e.strip()],
            "organization": org.strip(),
        })
    return contacts


# --------------------------------------------------------------------------- #
# Duplicate detection
# --------------------------------------------------------------------------- #

def detect_duplicates_by_phone(contacts: list[dict] | None = None) -> list[list[dict]]:
    """Group contacts sharing any normalized phone number."""
    if contacts is None:
        contacts = scan_contacts()
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in contacts:
        seen_phones: set[str] = set()
        for phone in c.get("phones", []):
            norm = _normalize_phone(phone)
            if len(norm) < 7 or norm in seen_phones:
                continue
            seen_phones.add(norm)
            buckets[norm].append(c)
    # Deduplicate: a contact with two of its own phones in a bucket should appear once
    result = []
    for phone, group in buckets.items():
        uniq = {c["id"]: c for c in group}
        if len(uniq) >= 2:
            result.append(list(uniq.values()))
    return result


def detect_duplicates_by_email(contacts: list[dict] | None = None) -> list[list[dict]]:
    """Group contacts sharing any (case-insensitive) email address."""
    if contacts is None:
        contacts = scan_contacts()
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in contacts:
        for email in c.get("emails", []):
            norm = _normalize_email(email)
            if "@" not in norm:
                continue
            buckets[norm].append(c)
    result = []
    for email, group in buckets.items():
        uniq = {c["id"]: c for c in group}
        if len(uniq) >= 2:
            result.append(list(uniq.values()))
    return result


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def export_duplicates_report(
    contacts: list[dict] | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Write a Markdown report grouping phone- and email-based duplicates.

    Contacts.app has no scriptable merge — the user must manually merge via
    Card → Look for Duplicates, or delete the extra entries.
    """
    out_dir = out_dir or common.DEFAULT_OUTPUT_DIR
    if contacts is None:
        contacts = scan_contacts()

    phone_groups = detect_duplicates_by_phone(contacts)
    email_groups = detect_duplicates_by_email(contacts)

    def _group_rows(groups):
        rows = []
        for i, group in enumerate(groups, 1):
            for c in group:
                rows.append({
                    "group": f"#{i}",
                    "name": c["full_name"] or "(no name)",
                    "phones": ", ".join(c["phones"][:3]),
                    "emails": ", ".join(c["emails"][:2]),
                    "org": c["organization"],
                })
        return rows

    return common.write_markdown_report(
        "Contacts Duplicates Report",
        [
            (
                f"Phone Duplicates ({len(phone_groups)} groups)",
                _group_rows(phone_groups),
                ["group", "name", "phones", "emails", "org"],
            ),
            (
                f"Email Duplicates ({len(email_groups)} groups)",
                _group_rows(email_groups),
                ["group", "name", "phones", "emails", "org"],
            ),
        ],
        out_dir,
        prefix="contacts-duplicates",
    )
