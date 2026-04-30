"""Messages (iMessage/SMS) cleanup module.

Public API:
- scan(db_path) -> {"spam": [...], "normal": [...], "unknown": [...]}
- classify(chat_id, last_text) -> ("spam"|"normal"|"unknown", reason)
- batch_delete(targets, *, dry_run=True, keep_exact=()) -> DeleteResult
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import common

DEFAULT_DB = Path.home() / "Library" / "Messages" / "chat.db"


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(chat_id: str, last_text: str | None) -> tuple[str, str]:
    """Return (label, reason) for a chat. label ∈ {spam, normal, unknown}."""
    if common.is_protected(chat_id):
        return "normal", "protected by whitelist"

    is_spam, reason = common.looks_like_spam(chat_id, last_text)
    if is_spam:
        return "spam", reason

    normalized = common.normalize_phone(chat_id).replace("+86", "").replace("+", "")
    if normalized.isdigit() and 4 <= len(normalized) <= 6:
        return "unknown", f"short code ({len(normalized)} digits)"
    if "@" in chat_id:
        return "unknown", "email sender — manual review"
    return "unknown", "uncategorized"


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #


def _apple_epoch_iso(ns: int | None) -> str | None:
    if not ns:
        return None
    return datetime.fromtimestamp(ns / 1e9 + 978307200).isoformat(timespec="seconds")


def scan(db_path: Path | None = None) -> dict:
    """Open chat.db read-only and classify every conversation.

    Returns {"spam": [...], "normal": [...], "unknown": [...]}.
    Raises FileNotFoundError or sqlite3.OperationalError (FDA missing).
    """
    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                c.ROWID,
                c.chat_identifier,
                c.guid,
                c.display_name,
                COUNT(cmj.message_id) AS msg_count,
                MAX(m.date) AS last_date,
                (SELECT text FROM message m2
                 JOIN chat_message_join cmj2 ON m2.ROWID = cmj2.message_id
                 WHERE cmj2.chat_id = c.ROWID
                 ORDER BY m2.date DESC LIMIT 1) AS last_text,
                (SELECT length(m3.attributedBody) FROM message m3
                 JOIN chat_message_join cmj3 ON m3.ROWID = cmj3.message_id
                 WHERE cmj3.chat_id = c.ROWID
                 ORDER BY m3.date DESC LIMIT 1) AS last_ab_len
            FROM chat c
            LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
            LEFT JOIN message m ON m.ROWID = cmj.message_id
            GROUP BY c.ROWID
            ORDER BY last_date DESC
            """
        )
        classified: dict[str, list[dict]] = {"spam": [], "normal": [], "unknown": []}
        for row in cur.fetchall():
            rowid, cid, guid, display, msg_count, last_date, last_text, ab_len = row
            label, reason = classify(cid or "", last_text)
            classified[label].append(
                {
                    "rowid": rowid,
                    "chat_id": cid,
                    "guid": guid,
                    "display_name": display,
                    "msg_count": msg_count,
                    "last_date": _apple_epoch_iso(last_date),
                    "last_text": (last_text or "")[:120] if last_text else None,
                    "last_ab_len": ab_len,
                    "reason": reason,
                }
            )
        return classified
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# UI automation — batch delete
# --------------------------------------------------------------------------- #


@dataclass
class DeleteResult:
    deleted: list[str] = field(default_factory=list)
    skipped_protected: list[str] = field(default_factory=list)
    halted_on: str | None = None
    error: str | None = None


def _current_window_name() -> str:
    """Return the title of Messages' front window (= currently selected chat_id)."""
    return common.osa(
        '''
        tell application "System Events"
            tell process "Messages"
                try
                    return name of window 1
                on error
                    return ""
                end try
            end tell
        end tell
        '''
    )


def _clear_pending_sheet() -> bool:
    """Cancel any lingering confirmation sheet to avoid accidental delete."""
    try:
        result = common.osa(
            '''
            tell application "System Events"
                tell process "Messages"
                    if (count of windows) = 0 then return "NO_WINDOW"
                    if (count of sheets of window 1) > 0 then
                        repeat with b in buttons of sheet 1 of window 1
                            try
                                if (title of b as string) is "取消" then
                                    click b
                                    return "CANCELED"
                                end if
                            end try
                        end repeat
                    end if
                    return "NO_SHEET"
                end tell
            end tell
            '''
        )
        return result == "CANCELED"
    except common.AppleScriptError:
        return False


def _delete_current_chat() -> tuple[bool, str]:
    """Invoke the Delete Conversation menu and click the strict-match '删除' button."""
    result = common.osa(
        '''
        tell application "Messages" to activate
        delay 0.2
        tell application "System Events"
            tell process "Messages"
                try
                    set delItem to menu item "删除对话…" of menu 1 of menu bar item "对话" of menu bar 1
                    if not (enabled of delItem) then return "ERR:MENU_DISABLED"
                    click delItem
                    delay 1.0
                    if (count of sheets of window 1) > 0 then
                        repeat with b in buttons of sheet 1 of window 1
                            try
                                if (title of b as string) is "删除" then
                                    click b
                                    delay 1.2
                                    try
                                        return "OK:" & (name of window 1)
                                    on error
                                        return "OK:NONE"
                                    end try
                                end if
                            end try
                        end repeat
                        return "ERR:NO_DELETE_BTN"
                    end if
                    return "ERR:NO_SHEET"
                on error errMsg
                    return "ERR:" & errMsg
                end try
            end tell
        end tell
        ''',
        timeout=20,
    )
    if result.startswith("OK:"):
        return True, result[3:]
    return False, result


def _switch(direction: str) -> str:
    key = "]" if direction == "next" else "["
    common.osa(
        f'''
        tell application "Messages" to activate
        delay 0.1
        tell application "System Events"
            tell process "Messages"
                keystroke "{key}" using {{command down, shift down}}
            end tell
        end tell
        '''
    )
    time.sleep(0.7)
    return _current_window_name()


def batch_delete(
    targets: Iterable[str],
    *,
    dry_run: bool = True,
    keep_exact: Iterable[str] = (),
    max_iterations: int = 700,
    on_progress=None,
) -> DeleteResult:
    """Walk the Messages sidebar, deleting chats whose id is in `targets`.

    Uses Messages.app's auto-advance-after-delete behaviour.
    Always halts rather than risks deleting a non-whitelisted unknown chat.
    """
    target_set = set(targets)
    keep_exact = frozenset(keep_exact)
    result = DeleteResult()

    seen: list[str] = []
    for _ in range(max_iterations):
        _clear_pending_sheet()
        cur = _current_window_name()
        if not cur:
            break

        seen.append(cur)
        if len(seen) > 5 and all(n == cur for n in seen[-5:]):
            result.halted_on = cur
            result.error = "stuck_on_same_chat"
            break

        if on_progress:
            on_progress({"current": cur, "deleted_count": len(result.deleted)})

        if common.is_protected(cur, extra_exact=keep_exact):
            if cur not in result.skipped_protected:
                result.skipped_protected.append(cur)
            new_name = _switch("next")
            if new_name == cur:
                new_name = _switch("prev")
                if new_name == cur:
                    result.halted_on = cur
                    result.error = "cannot_advance"
                    break
            continue

        normalized = common.normalize_phone(cur)
        is_target = cur in target_set or normalized in target_set
        is_inline_spam, _ = common.looks_like_spam(cur, None)

        if is_target or is_inline_spam:
            if dry_run:
                result.deleted.append(cur)
                _switch("next")
                continue
            ok, after = _delete_current_chat()
            if ok:
                result.deleted.append(cur)
                time.sleep(0.4)
            else:
                _clear_pending_sheet()
                _switch("next")
                if _current_window_name() == cur:
                    result.halted_on = cur
                    result.error = f"delete_failed: {after}"
                    break
        else:
            result.halted_on = cur
            result.error = "uncertain_chat_requires_review"
            break

    return result
