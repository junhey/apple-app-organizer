"""
Messages (iMessage/SMS) module.

Data source:
  - ~/Library/Messages/chat.db  (SQLite, read-only)
  - Messages.app UI scripting   (for delete via menu)

Safety: Deleted chats go to "Recently Deleted" (30-day recovery window).

Known pitfalls:
  - AppleScript 'delete' verb is broken (error -10000) → must use menu UI
  - Chinese input requires clipboard + Cmd+V, not keystroke
  - Window title for chat shows numbers WITHOUT spaces; DB stores WITHOUT spaces
  - Confirmation sheet has three buttons — match title is "删除" strictly
"""

import sqlite3
import subprocess
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .utils import normalize_phone, truncate, write_json, write_markdown

CHAT_DB = Path.home() / "Library/Messages/chat.db"

# Number patterns that are almost certainly NOT real contacts
KNOWN_SPAM_PREFIXES = (
    "+1",  # US/CA spam
    "+44",  # UK spam
    "+852", "+853", "+886",  # HK/MO/TW
    # Chinese mobile prefixes (suspicious if not in whitelist)
    "130", "131", "132", "133", "134", "135", "136", "137", "138", "139",
    "147", "148",
    "150", "151", "152", "153", "155", "156", "157", "158", "159",
    "166",
    "170", "171", "172", "173",
    "180", "181", "182", "183", "184", "185", "186", "187", "188", "189",
    "190", "191", "193", "195", "196", "197", "198", "199",
)

# Message content keywords suggesting promotional/spam content
SPAM_KEYWORDS = [
    "【", "★", "☆", "◆", "●", "►",
    "秒杀", "限时", "优惠", "折扣", "促销", "抢购",
    "博彩", "彩票", "赌博",
    "贷款", "套现", "代还",
    "发票", "代开",
    "加微", "加我", "私信", "回复TD", "回复T",
    "unsubscribe", "click here", "opt out",
]

MAX_UI_LOOP = 5  # Safety: stop after 5 identical window titles


def check_permissions() -> bool:
    if not CHAT_DB.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM chat")
        conn.close()
    except Exception:
        return False
    # Also check Automation permission via osascript
    result = subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to get UI elements enabled'],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _get_db_connection():
    return sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)


def _decode_attributed_body(raw: bytes) -> str:
    """Decode NSAttributedString data from attributedBody blob (simplified)."""
    # The attributedBody field stores an NSAttributedString archived data.
    # We do a best-effort UTF-8 decode; the actual string may be further
    # encoded. For spam keyword matching, we just try decode() on whatever
    # bytes are there.
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _chat_display_id(chat_row: tuple) -> str:
    """Return the display identifier for a chat row (handle or group id)."""
    # chat_id is an integer; identifier is TEXT (e.g. "chat123456789")
    # We use the chat's display name if available
    return str(chat_row[0])


def _get_display_name(chat_id: int, conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT display_name FROM chat WHERE ROWID = ?", (chat_id,)
    ).fetchone()
    return row[0] if row else ""


def _get_contact_idents(chat_id: int, conn: sqlite3.Connection) -> list[str]:
    """Return list of phone numbers / emails associated with a chat."""
    rows = conn.execute(
        """SELECT c1.identifier
           FROM chat_message_join cmj
           JOIN message m ON m.ROWID = cmj.message_id
           JOIN chat_message_join cmj2 ON cmj2.chat_id = cmj.chat_id
           JOIN message m2 ON m2.ROWID = cmj2.message_id
           WHERE cmj.message_id = (SELECT MIN(message_id FROM chat_message_join WHERE chat_id = ?))
        """,
        (chat_id,),
    ).fetchall()
    # Actually just grab handle identifier from message
    rows = conn.execute(
        """SELECT m.handle_id, h.id, h.uncanonicalized_id
           FROM chat_message_join cmj
           JOIN message m ON m.ROWID = cmj.message_id
           LEFT JOIN handle h ON h.ROWID = m.handle_id
           WHERE cmj.chat_id = ?
           LIMIT 1""",
        (chat_id,),
    ).fetchall()
    if not rows:
        return []
    _, canonical, uncanonical = rows[0]
    result = [x for x in [canonical, uncanonical] if x]
    return result


def scan(whitelist: Optional[dict] = None) -> list[dict]:
    """Scan chat.db for potentially spam/promotional conversations."""
    whitelist = whitelist or {}
    protected_phones = set(normalize_phone(p) for p in whitelist.get("phone_numbers", []))
    protected_numbers_raw = set(whitelist.get("phone_numbers", []))

    conn = _get_db_connection()
    chats = conn.execute(
        """SELECT c.ROWID, c.display_name, c.chat_identifier,
                  (SELECT COUNT(*) FROM chat_message_join cmj WHERE cmj.chat_id = c.ROWID) AS msg_count,
                  (SELECT MAX(m.date) FROM chat_message_join cmj2
                   JOIN message m ON m.ROWID = cmj2.message_id WHERE cmj2.chat_id = c.ROWID) AS last_date
           FROM chat c
           ORDER BY last_date DESC
           LIMIT 500"""
    ).fetchall()
    conn.close()

    results = []
    for row in chats:
        chat_id, display_name, chat_ident, msg_count, last_date = row
        if display_name and display_name.startswith("chat"):
            display_name = ""
        ident = chat_ident or display_name or f"chat_{chat_id}"
        norm = normalize_phone(ident)
        if norm in protected_phones:
            continue
        if ident in protected_numbers_raw:
            continue

        # Check for spam characteristics
        reasons = []
        if norm.startswith(KNOWN_SPAM_PREFIXES) and len(norm) >= 11:
            reasons.append("foreign/spam prefix")
        if display_name and any(kw in display_name for kw in SPAM_KEYWORDS):
            reasons.append("display name keyword")

        # Group chats are never treated as spam
        is_group = bool(display_name and display_name not in (chat_ident,))

        if not is_group and (reasons or norm.startswith(KNOWN_SPAM_PREFIXES)):
            results.append({
                "chat_id": chat_id,
                "display_name": display_name or "",
                "identifier": ident,
                "msg_count": msg_count,
                "last_date": datetime.fromtimestamp(last_date / 1e9).isoformat() if last_date else "",
                "reasons": "; ".join(reasons) or "suspicious prefix",
                "is_group": False,
            })
    return results


def _ui_delete_by_window_title(target_title: str, dry_run: bool = True) -> int:
    """
    Use UI Scripting to delete the Messages conversation whose window title
    matches target_title. Uses the menu: File → Delete Conversation… (删除对话…).
    Returns number of conversations deleted.
    """
    if dry_run:
        return 0
    loop_count = 0
    prev_title = ""
    deleted = 0
    while True:
        # Get frontmost window title
        script = 'tell application "Messages" to get name of front window'
        try:
            title = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except Exception:
            break

        if not title or title in (prev_title, "") or loop_count >= MAX_UI_LOOP:
            break

        # Check if it matches target
        if target_title in title:
            # Click File → Delete Conversation…
            delete_script = (
                'tell application "System Events"\n'
                '  tell process "Messages"\n'
                '    click menu item "删除对话…" of menu 1 of menu bar item "文件" of menu bar 1\n'
                '  end tell\n'
                'end tell'
            )
            try:
                subprocess.run(["osascript", "-e", delete_script], capture_output=True, timeout=5)
                deleted += 1
                time.sleep(0.5)
            except Exception:
                break
            loop_count += 1
        else:
            break
        prev_title = title
    return deleted


def clean(items: list[dict], dry_run: bool = True, whitelist: Optional[dict] = None) -> list[dict]:
    """
    Delete flagged conversations via Messages.app UI scripting.
    Each item must have 'identifier' (used as window title match).
    Deleted chats go to Recently Deleted (30-day recovery window).
    """
    deleted = []
    for item in items:
        ident = item.get("identifier", "")
        if not ident:
            continue
        # Find the window that matches this identifier
        count = _ui_delete_by_window_title(ident, dry_run=dry_run)
        if count > 0:
            deleted.append(item)
        time.sleep(0.3)
    return deleted


def generate_report(whitelist: Optional[dict] = None, output_dir: Path = Path("/tmp/apple-app-organizer")) -> Path:
    items = scan(whitelist=whitelist)
    lines = [
        "# Messages Cleanup Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        f"**Total flagged conversations:** {len(items)}",
        "",
        "## Flagged Conversations",
        "",
        "| # | Display Name | Identifier | Messages | Last Active | Reason |",
        "|---|--------------|-----------|----------|-------------|--------|",
    ]
    for i, item in enumerate(items, 1):
        lines.append(
            f"| {i} | {item['display_name'] or '(no name)'} "
            f"| `{item['identifier']}` | {item['msg_count']} "
            f"| {item['last_date'][:10] if item['last_date'] else '?'} "
            f"| {item['reasons']} |"
        )
    lines.append("")
    lines.append("## Recovery")
    lines.append("Deleted conversations are moved to **Recently Deleted** and recoverable for 30 days.")
    lines.append("To recover: open Messages → **Edit → Recently Deleted**.")
    path = output_dir / "messages_report.md"
    write_markdown(lines, path)
    return path


def add_cli_args(parser):
    parser.add_argument("--include-body", action="store_true",
                        help="Also scan message body text (slow for large DBs)")
