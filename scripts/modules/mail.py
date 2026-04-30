"""
Mail module.

Data source: Mail.app via AppleScript 'tell application "Mail"'.

Capabilities:
  - scan_mailboxes()           — list mailboxes with counts
  - classify_ads()             — flag messages as likely promotional
  - move_to_trash()            — move to Mail Trash (recoverable for 30 days)
  - detect_old_unread()        — find unread messages older than N months

Safety: All deletions go through Trash mailbox. 30-day recovery via
        Mailbox → Erased Items (or Trash → Erased Items on macOS Ventura+).
        NEVER use 'delete' directly — always 'move to mailbox id "Trash"' or
        'move to trash'.
"""

import subprocess
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .utils import write_markdown

DEFAULT_AD_KEYWORDS = [
    # Punctuation symbols common in spam
    "【", "★", "☆", "◆", "●", "►",
    # Chinese spam categories
    "秒杀", "限时", "优惠", "折扣", "促销", "抢购",
    "博彩", "彩票", "赌博", "赌场",
    "贷款", "套现", "代还", "无抵押",
    "发票", "代开", "开票",
    "加微", "加我", "私信", "回复TD", "回复T", "回T退订",
    "瘦身", "减肥", "纤体", "增粗", "延时",
    "成人", "色情", "裸聊",
    "投资", "理财", "高回报", "日化",
    # English spam
    "unsubscribe", "opt out", "click here", "free gift",
    "you have won", "congratulations", "act now",
    # Ad indicators
    "广告", "推广", "推广期", "优惠码",
]

AD_SENDER_PATTERNS = [
    "noreply@", "no-reply@", "autoreply@", "mailer-daemon@",
    "bounce@", "bounces@",
]


def check_permissions() -> bool:
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Mail" to get name of first mailbox'],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


def _run(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Mail AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def _mailbox_id(name: str) -> str:
    """Get the mailbox ID (internal path) by name."""
    script = (
        f'tell application "Mail"\n'
        f'  set mb to mailbox "{name}"\n'
        f'  return id of mb\n'
        f'end tell'
    )
    try:
        return _run(script)
    except Exception:
        return ""


def scan_mailboxes() -> list[dict]:
    """
    List all mailboxes with account, total message count, and unread count.
    """
    script = (
        'tell application "Mail"\n'
        '  set allMboxes to every mailbox\n'
        '  set resultList to {}\n'
        '  repeat with mb in allMboxes\n'
        '    set mbName to name of mb\n'
        '    set mbAccount to name of account of mb\n'
        '    set mbTotal to count of messages of mb\n'
        '    set mbUnread to count of unread messages of mb\n'
        '    copy {name:mbName, account:mbAccount, total:mbTotal, unread:mbUnread} '
        '      to end of resultList\n'
        '  end repeat\n'
        '  return resultList as JSON\n'
        'end tell'
    )
    try:
        return json.loads(_run(script))
    except Exception:
        return []


def classify_ads(
    mailbox_name: str = "INBOX",
    keyword_list: Optional[list[str]] = None,
    max_messages: int = 500,
) -> list[dict]:
    """
    Scan a mailbox and flag messages matching ad/promotional patterns.
    Returns list of { id, subject, sender, date, reason }.
    """
    keyword_list = keyword_list or DEFAULT_AD_KEYWORDS
    mb_id = _mailbox_id(mailbox_name)
    if not mb_id:
        return []

    script = (
        f'tell application "Mail"\n'
        f'  set msgs to messages of mailbox id "{mb_id}"\n'
        f'  set resultList to {{}}\n'
        f'  repeat with msg in msgs\n'
        f'    set msgId to id of msg\n'
        f'    set msgSubject to subject of msg\n'
        f'    set msgSender to sender of msg\n'
        f'    set msgDate to date received of msg\n'
        f'    set msgWasRead to was unread of msg\n'
        f'    copy {{id:msgId, subject:msgSubject, sender:msgSender, '
        f'          date:msgDate, wasUnread:msgWasRead}} to end of resultList\n'
        f'    if (count of resultList) ≥ {max_messages} then exit repeat\n'
        f'  end repeat\n'
        f'  return resultList as JSON\n'
        f'end tell'
    )
    try:
        messages = json.loads(_run(script))
    except Exception:
        return []

    results = []
    for msg in messages:
        subject = msg.get("subject", "") or ""
        sender = msg.get("sender", "") or ""

        reasons = []
        # Keyword match
        for kw in keyword_list:
            if kw in subject or kw in sender:
                reasons.append(f"keyword:'{kw}'")
                break
        # Sender pattern match
        sender_lower = sender.lower()
        if any(p in sender_lower for p in AD_SENDER_PATTERNS):
            reasons.append("no-reply/bounce sender")
        # All-caps subject (shouting)
        if subject.isupper() and len(subject) > 20:
            reasons.append("all-caps subject")

        if reasons:
            results.append({
                "id": msg.get("id", ""),
                "subject": subject,
                "sender": sender,
                "date": msg.get("date", ""),
                "was_unread": msg.get("wasUnread", False),
                "reason": "; ".join(reasons),
            })
    return results


def move_to_trash(
    message_ids: list[str],
    dry_run: bool = True,
) -> list[str]:
    """
    Move messages to the system Trash mailbox.
    Messages stay in Trash for ~30 days before permanent deletion by Mail.

    Args:
        message_ids: Mail message IDs (integer strings from Mail AppleScript)
        dry_run: If True, returns the IDs that would be moved without mutating.

    Returns:
        List of successfully moved message IDs.
    """
    if dry_run:
        return message_ids

    trash_id = _mailbox_id("Trash")
    if not trash_id:
        raise RuntimeError("Could not find Trash mailbox")

    moved = []
    for mid in message_ids:
        script = (
            f'tell application "Mail"\n'
            f'  set theMsg to message id {mid}\n'
            f'  move theMsg to mailbox id "{trash_id}"\n'
            f'end tell'
        )
        try:
            _run(script)
            moved.append(mid)
        except Exception:
            pass
        time.sleep(0.1)  # Avoid flooding Mail with rapid moves
    return moved


def detect_old_unread(
    older_than_months: int = 12,
    mailbox_name: str = "INBOX",
) -> list[dict]:
    """
    Find messages that have been unread for longer than older_than_months.
    These are likely abandoned subscriptions or forgotten notifications.
    """
    cutoff = datetime.now() - timedelta(days=older_than_months * 30)
    cutoff_str = cutoff.strftime("%a, %d %b %Y %H:%M:%S")

    mb_id = _mailbox_id(mailbox_name)
    if not mb_id:
        return []

    script = (
        f'tell application "Mail"\n'
        f'  set unreadMsgs to (messages of mailbox id "{mb_id}" '
        f'    whose (was unread is true))\n'
        f'  set resultList to {{}}\n'
        f'  repeat with msg in unreadMsgs\n'
        f'    set msgDate to date received of msg\n'
        f'    if msgDate < date "{cutoff_str}" then\n'
        f'      set msgId to id of msg\n'
        f'      set msgSubject to subject of msg\n'
        f'      set msgSender to sender of msg\n'
        f'      copy {{id:msgId, subject:msgSubject, sender:msgSender, '
        f'            date:msgDate}} to end of resultList\n'
        f'    end if\n'
        f'  end repeat\n'
        f'  return resultList as JSON\n'
        f'end tell'
    )
    try:
        return json.loads(_run(script))
    except Exception:
        return []


# ── Module interface ─────────────────────────────────────────────────────────

def scan(whitelist: Optional[dict] = None, mailbox: str = "INBOX") -> list[dict]:
    """Alias for classify_ads() — scan a mailbox for ads."""
    return classify_ads(mailbox_name=mailbox)


def generate_report(
    whitelist: Optional[dict] = None,
    output_dir: Path = Path("/tmp/apple-app-organizer"),
    mailbox: str = "INBOX",
    older_than_months: int = 12,
) -> Path:
    ad_messages = classify_ads(mailbox_name=mailbox)
    old_unread = detect_old_unread(older_than_months=older_than_months, mailbox_name=mailbox)

    lines = [
        "# Mail Cleanup Report",
        f"Generated: {datetime.now().isoformat()}",
        f"Mailbox: {mailbox}",
        "",
        f"**Likely promotional messages:** {len(ad_messages)}",
        f"**Old unread (>{older_than_months} months):** {len(old_unread)}",
        "",
        "## Promotional Messages",
        "",
        "| # | Subject | Sender | Date | Reason |",
        "|---|---------|--------|------|--------|",
    ]
    for i, msg in enumerate(ad_messages[:100], 1):
        lines.append(
            f"| {i} | {msg['subject'][:60]} | {msg['sender'][:40]} | "
            f"{str(msg.get('date',''))[:10]} | {msg['reason']} |"
        )
    lines.append("")
    lines.append(f"## Old Unread (>{older_than_months} months)")
    lines.append("")
    lines.append("| # | Subject | Sender | Date Received |")
    lines.append("|---|---------|--------|---------------|")
    for i, msg in enumerate(old_unread[:100], 1):
        lines.append(
            f"| {i} | {msg['subject'][:60]} | {msg['sender'][:40]} | "
            f"{str(msg.get('date',''))[:10]} |"
        )
    lines.append("")
    lines.append("## Recovery")
    lines.append(
        f"Deleted messages are moved to **Trash** and kept for ~30 days. "
        "To recover: Mailbox → **Erased Items** (macOS Ventura+)."
    )
    lines.append(
        "After 30 days Mail permanently deletes Trash automatically."
    )
    path = output_dir / "mail_report.md"
    write_markdown(lines, path)
    return path


def clean(
    items: list[dict],
    dry_run: bool = True,
    whitelist: Optional[dict] = None,
) -> list[dict]:
    """
    Move flagged messages to Trash.
    Returns list of successfully moved message IDs.
    """
    ids = [item["id"] for item in items if "id" in item]
    moved_ids = move_to_trash(ids, dry_run=dry_run)
    return [{"id": mid} for mid in moved_ids]


def add_cli_args(parser):
    parser.add_argument("--mailbox", type=str, default="INBOX",
                        help="Mailbox to scan (default: INBOX)")
    parser.add_argument("--older-than-months", type=int, default=12,
                        help="Flag unread messages older than N months (default: 12)")
    parser.add_argument("--old-unread", action="store_true",
                        help="Also scan for old unread messages")
