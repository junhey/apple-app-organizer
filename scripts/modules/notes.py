"""
Notes module.

Data source:
  ~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite  (read-only)
  Notes.app AppleScript (for archive/delete)

Safety: Notes are moved to the "Archive" folder (Notes.app built-in recovery).
       Encrypted notes cannot be read — skipped automatically.
"""

import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .utils import write_json, write_markdown

NOTE_STORE = (
    Path.home()
    / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
)

DEFAULT_AD_KEYWORDS = [
    "【", "★", "限时", "秒杀", "优惠", "折扣", "促销", "抢购",
    "博彩", "贷款", "套现", "加微", "unsubscribe",
]


def check_permissions() -> bool:
    if not NOTE_STORE.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{NOTE_STORE}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM note")
        conn.close()
    except Exception:
        return False
    # Check Notes AppleScript access
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Notes" to get name of first note'],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode == 0


def _get_db_connection():
    return sqlite3.connect(f"file:{NOTE_STORE}?mode=ro", uri=True)


def scan(whitelist: Optional[dict] = None, include_body: bool = False) -> list[dict]:
    """
    Detect duplicate and empty notes.
    Returns list of dicts with id, title, preview, reason, is_encrypted.
    """
    conn = _get_db_connection()

    # note table: id (TEXT UUID), title (TEXT), body (BLOB/NSAttributedString), ...
    # encrypted_note_id: non-null → encrypted, cannot read
    rows = conn.execute(
        """SELECT id, title, encrypted_note_id, created_date, modified_date
           FROM note
           ORDER BY modified_date DESC
           LIMIT 2000"""
    ).fetchall()

    # Build title → list of (id, created, modified) for duplicate detection
    title_map: dict[str, list] = {}
    for row in rows:
        note_id, title, enc_id, created, modified = row
        key = (title or "").strip().lower()
        if key:
            title_map.setdefault(key, []).append((note_id, title, created, modified))

    results = []
    seen_ids: set[str] = set()

    for note_id, title, enc_id, created, modified in rows:
        if note_id in seen_ids:
            continue
        reason = None

        if enc_id is not None:
            reason = "encrypted"
        elif not title and not include_body:
            reason = "empty (no title)"
        elif title:
            # Check duplicate
            key = title.strip().lower()
            if key in title_map and len(title_map[key]) > 1:
                reason = f"duplicate title (×{len(title_map[key])})"

        if reason:
            results.append({
                "id": note_id,
                "title": title or "(no title)",
                "created": datetime.fromtimestamp(created / 1e9).isoformat() if created else "",
                "modified": datetime.fromtimestamp(modified / 1e9).isoformat() if modified else "",
                "reason": reason,
                "is_encrypted": enc_id is not None,
            })
            seen_ids.add(note_id)

    conn.close()
    return results


def _notes_archive(note_id: str, dry_run: bool = True) -> bool:
    """Move note to Archive folder via Notes AppleScript."""
    if dry_run:
        return True
    script = (
        f'tell application "Notes"\n'
        f'  set theNote to note id "{note_id}"\n'
        f'  move theNote to folder "Archive"\n'
        f'end tell'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _notes_delete(note_id: str, dry_run: bool = True) -> bool:
    """Delete note permanently via Notes AppleScript."""
    if dry_run:
        return True
    script = (
        f'tell application "Notes"\n'
        f'  set theNote to note id "{note_id}"\n'
        f'  delete theNote\n'
        f'end tell'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def clean(items: list[dict], dry_run: bool = True, whitelist: Optional[dict] = None) -> list[dict]:
    """
    Archive duplicate/empty notes. Encrypted notes are never touched.
    Returns list of successfully cleaned note IDs.
    """
    deleted = []
    for item in items:
        if item.get("is_encrypted"):
            continue  # Never delete encrypted notes
        note_id = item["id"]
        if _notes_archive(note_id, dry_run=dry_run):
            deleted.append(item)
        time.sleep(0.2)
    return deleted


def generate_report(
    whitelist: Optional[dict] = None,
    output_dir: Path = Path("/tmp/apple-app-organizer"),
    include_body: bool = False,
) -> Path:
    items = scan(whitelist=whitelist, include_body=include_body)
    lines = [
        "# Notes Cleanup Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        f"**Total flagged notes:** {len(items)}",
        "",
        "## Flagged Notes",
        "",
        "| # | Title | Created | Modified | Reason |",
        "|---|-------|---------|---------|--------|",
    ]
    for i, item in enumerate(items, 1):
        lines.append(
            f"| {i} | {item['title'][:60]} | "
            f"{item['created'][:10] if item['created'] else '?'} | "
            f"{item['modified'][:10] if item['modified'] else '?'} | "
            f"{item['reason']} |"
        )
    lines.append("")
    lines.append("## Recovery")
    lines.append("Archived notes are in **Archive** folder in Notes.app and recoverable immediately.")
    lines.append("**Encrypted notes are never touched.**")
    path = output_dir / "notes_report.md"
    write_markdown(lines, path)
    return path


def add_cli_args(parser):
    parser.add_argument("--include-body", action="store_true",
                        help="Also include empty-body notes in scan")
