"""Mail (Mail.app) cleanup module.

Public API:
- scan_mailboxes()        -> [{"name", "account", "total", "unread"}]
- classify_ads(mailbox, keywords) -> [{"id", "subject", "sender", "date"}]
- move_to_trash(message_ids, account, dry_run=True) -> BatchResult
- detect_old_unread(older_than_months) -> list of likely-abandoned threads

Safety: never issues `delete message`. Always `move ... to trash mailbox`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import common


DEFAULT_AD_KEYWORDS = (
    "unsubscribe",
    "退订", "促销", "限时", "折扣", "立减", "秒杀", "优惠券",
    "offer", "discount", "deal", "sale", "limited",
    "newsletter", "免费试用", "free trial",
)


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
# Scan
# --------------------------------------------------------------------------- #

def scan_mailboxes() -> list[dict]:
    """Return all mailboxes across all accounts with total+unread counts."""
    script = r"""
    tell application "Mail"
        set output to ""
        repeat with acc in accounts
            set accName to name of acc as string
            repeat with mb in mailboxes of acc
                try
                    set mbName to name of mb as string
                    set totalCount to count of messages of mb
                    set unreadCount to count of (messages of mb whose read status is false)
                    set output to output & mbName & tab & accName & tab & totalCount & tab & unreadCount & linefeed
                end try
            end repeat
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=90)
    result = []
    for row in _parse_lines(stdout, 4):
        name, account, total, unread = row
        result.append({
            "name": name,
            "account": account,
            "total": int(total),
            "unread": int(unread),
        })
    return result


# --------------------------------------------------------------------------- #
# Ad classification
# --------------------------------------------------------------------------- #

def classify_ads(
    mailbox_name: str,
    account: str,
    keywords: Iterable[str] = DEFAULT_AD_KEYWORDS,
    *,
    limit: int = 500,
) -> list[dict]:
    """Return messages in the given mailbox whose subject/sender/body matches any keyword."""
    # To keep the AppleScript simple and fast we only filter by subject here,
    # then post-filter on sender in Python.
    kw_list = list(keywords)
    # AppleScript: build an OR filter for the 'subject contains' test
    # (Apple Mail can't compose complex predicates easily, so we fetch
    #  all messages and filter in Python.)
    mb_escaped = mailbox_name.replace('"', '\\"')
    acc_escaped = account.replace('"', '\\"')
    script = f"""
    tell application "Mail"
        set output to ""
        try
            set mb to mailbox "{mb_escaped}" of account "{acc_escaped}"
            set msgs to messages of mb
            set n to count of msgs
            if n > {limit} then set n to {limit}
            repeat with i from 1 to n
                try
                    set m to item i of msgs
                    set output to output & (id of m as string) & tab & ¬
                        (subject of m as string) & tab & ¬
                        (sender of m as string) & tab & ¬
                        (date received of m as string) & linefeed
                end try
            end repeat
        end try
        return output
    end tell
    """
    stdout = common.osa(script, timeout=120)
    candidates = []
    for row in _parse_lines(stdout, 4):
        mid, subject, sender, date = row
        subj_lower = subject.lower()
        sender_lower = sender.lower()
        hits = [kw for kw in kw_list if kw.lower() in subj_lower or kw.lower() in sender_lower]
        if hits:
            candidates.append({
                "id": mid,
                "subject": subject,
                "sender": sender,
                "date": date,
                "matched": hits[:3],
            })
    return candidates


# --------------------------------------------------------------------------- #
# Trash (safe delete)
# --------------------------------------------------------------------------- #

@dataclass
class BatchResult:
    targeted: list[str] = field(default_factory=list)
    trashed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = True


def move_to_trash(
    message_ids: Iterable[str],
    account: str,
    source_mailbox: str,
    *,
    dry_run: bool = True,
    on_progress: Callable[[dict], None] | None = None,
) -> BatchResult:
    """Move the given messages from source_mailbox to the account's trash mailbox.

    Never uses `delete message` — move-to-trash is recoverable (30 days typical).
    """
    ids = list(message_ids)
    result = BatchResult(targeted=list(ids), dry_run=dry_run)

    total = len(ids)
    for i, mid in enumerate(ids, 1):
        if on_progress:
            on_progress({"index": i, "total": total, "id": mid})
        if dry_run:
            result.trashed.append(mid)
            continue
        mb_esc = source_mailbox.replace('"', '\\"')
        acc_esc = account.replace('"', '\\"')
        mid_esc = str(mid).replace('"', '\\"')
        script = f"""
        tell application "Mail"
            try
                set acc to account "{acc_esc}"
                set mb to mailbox "{mb_esc}" of acc
                set trashMb to missing value
                repeat with tmb in mailboxes of acc
                    try
                        set mname to name of tmb as string
                        if mname is "Deleted Messages" or mname is "Trash" or mname contains "Trash" then
                            set trashMb to tmb
                            exit repeat
                        end if
                    end try
                end repeat
                if trashMb is missing value then return "ERR:NO_TRASH_MAILBOX"
                set msg to first message of mb whose id is {mid_esc}
                move msg to trashMb
                return "OK"
            on error errMsg
                return "ERR:" & errMsg
            end try
        end tell
        """
        ret = common.osa(script, timeout=15)
        if ret == "OK":
            result.trashed.append(mid)
        else:
            result.failed.append((mid, ret))
    return result


# --------------------------------------------------------------------------- #
# Old unread detection
# --------------------------------------------------------------------------- #

def detect_old_unread(older_than_months: int = 12) -> list[dict]:
    """Find unread messages older than N months across all mailboxes."""
    days = older_than_months * 30
    script = f"""
    tell application "Mail"
        set cutoff to (current date) - ({days} * days)
        set output to ""
        repeat with acc in accounts
            set accName to name of acc as string
            repeat with mb in mailboxes of acc
                try
                    set mbName to name of mb as string
                    repeat with m in (messages of mb whose read status is false and date received < cutoff)
                        try
                            set output to output & (id of m as string) & tab & ¬
                                (subject of m as string) & tab & ¬
                                (sender of m as string) & tab & ¬
                                (date received of m as string) & tab & ¬
                                accName & tab & mbName & linefeed
                        end try
                    end repeat
                end try
            end repeat
        end repeat
        return output
    end tell
    """
    stdout = common.osa(script, timeout=180)
    result = []
    for row in _parse_lines(stdout, 6):
        mid, subject, sender, date, acc, mb = row
        result.append({
            "id": mid,
            "subject": subject,
            "sender": sender,
            "date": date,
            "account": acc,
            "mailbox": mb,
        })
    return result
