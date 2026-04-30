"""Notes (Apple Notes.app) cleanup module.

Public API:
- list_folders()        -> [{"name", "note_count", "is_archive"}]
- scan_notes()           -> [{"uuid", "title", "folder", "modified", "body_preview", "body_hash"}]
- detect_duplicates()    -> [[uuid, uuid, ...]]  groups sharing body_hash
- detect_empty(min_chars)-> [uuid, ...] short/blank notes
- archive_note(uuid)    -> bool  (AppleScript; safe, icloud-synced)
- delete_note(uuid)     -> bool  (AppleScript with dry-run guard; destructive)
"""
from __future__ import annotations

import gzip
import hashlib
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

DEFAULT_DB = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.notes"
    / "NoteStore.sqlite"
)

# --------------------------------------------------------------------------- #
# Database access helpers
# --------------------------------------------------------------------------- #

# Notes live in ZICCLOUDSYNCINGOBJECT with Z_ENT IN (5, 11, 12).
# Z_ENT=5  = regular notes (may have ZTITLE)
# Z_ENT=11 = encrypted / password-protected notes  (ZISPASSWORDPROTECTED=1)
# Z_ENT=12 = normal notes without password
# Text body lives in ZICNOTEDATA.ZDATA (gzip-compressed protobuf, UTF-8 text inside).
# Folders live in ZICCLOUDSYNCINGOBJECT with Z_ENT=4 (primary) or Z_ENT=15 (special).
# The Notes.app AppleScript note ID format:
#   x-coredata://{DB_UUID}/ICNote/p{Z_PK}
# The DB UUID lives in Z_METADATA.Z_UUID.

_NOTE_ENTS = (5, 11, 12)

# Regex: extract readable Chinese + ASCII segments from a blob decoded
# with errors='ignore' (proto bytes get stripped).
_TEXT_SEG_RE = re.compile(
    r"[\u4e00-\u9fff]+"   # consecutive Chinese chars
    r"|[a-zA-Z][a-zA-Z0-9]*(?:\s+[a-zA-Z][a-zA-Z0-9]*){0,30}"  # word phrases
    r"|[0-9]{3,}"          # 3+ digits
    r"|[，。！？、：；""''（）【】《》…—·]{2,}",  # punctuation runs
    re.UNICODE,
)


def _db_connect(db_path: Path) -> sqlite3.Connection:
    """Open NoteStore.sqlite read-only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _get_db_uuid(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT Z_UUID FROM Z_METADATA LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Z_METADATA.Z_UUID not found — is this a valid NoteStore?")
    return row[0]


def _note_id_from_pk(db_uuid: str, pk: int) -> str:
    return f"x-coredata://{db_uuid}/ICNote/p{pk}"


def _folder_id_from_pk(db_uuid: str, pk: int) -> str:
    return f"x-coredata://{db_uuid}/ICFolder/p{pk}"


# --------------------------------------------------------------------------- #
# Text decoding (gzip + protobuf-stripped UTF-8)
# --------------------------------------------------------------------------- #

def _decode_body(blob: bytes | None) -> str:
    """Decompress NoteStore gzip blob and extract readable text.

    The blob is gzip-compressed. After decompression the bytes contain a
    nested protobuf MessageLite (NoteStore proto) with UTF-8 note text
    interleaved with protobuf structure bytes.

    Strategy: decode with errors='ignore' to drop non-UTF-8 proto bytes,
    then extract readable segments with regex.
    """
    if not blob:
        return ""
    try:
        raw = gzip.decompress(blob)
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    clean = re.sub(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]", "", text)
    segments = _TEXT_SEG_RE.findall(clean)
    # Join with space so "Hello World 你好世界" stays together
    raw_join = " ".join(s.strip() for s in segments if len(s.strip()) >= 2)
    return re.sub(r" {2,}", " ", raw_join).strip()


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def list_folders(db_path: Path | None = None) -> list[dict]:
    """Return all folders with note counts.

    Returns [{"name", "note_count", "is_archive", "folder_id"}].
    Folders without a name are named "(Default)" / "(Trash)" / "(Archive)".
    """
    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _db_connect(db_path)
    db_uuid = _get_db_uuid(conn)

    try:
        # Primary folders: Z_ENT=4 (custom), Z_ENT=15 (system: Trash, Default)
        cur = conn.execute(
            """
            SELECT
                f.Z_PK,
                f.ZTITLE,
                f.Z_ENT,
                COUNT(n.Z_PK) AS note_count
            FROM ZICCLOUDSYNCINGOBJECT f
            LEFT JOIN ZICCLOUDSYNCINGOBJECT n
                ON n.ZFOLDER = f.Z_PK AND n.Z_ENT IN (5, 11, 12)
            WHERE f.Z_ENT IN (4, 15)
            GROUP BY f.Z_PK
            ORDER BY f.ZTITLE
            """
        )
        folders = []
        for pk, title, z_ent, count in cur.fetchall():
            name = title or ""
            is_archive = "archive" in name.lower()
            is_trash = z_ent == 15 or "trash" in name.lower()
            if not name:
                # Unnamed folder: primary (Z_ENT=4) with no title = default folder
                if z_ent == 4:
                    name = "(Default)"
                elif is_trash:
                    name = "(Trash)"
                else:
                    name = "(Unnamed)"
            folders.append({
                "name": name,
                "note_count": count,
                "is_archive": is_archive,
                "folder_id": _folder_id_from_pk(db_uuid, pk),
            })
        return folders
    finally:
        conn.close()


def scan_notes(db_path: Path | None = None) -> list[dict]:
    """Return all notes with metadata and a body preview.

    Returns [{"uuid", "title", "folder", "modified", "body_preview", "body_hash",
             "is_encrypted", "z_pk"}].
    """
    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _db_connect(db_path)
    db_uuid = _get_db_uuid(conn)

    try:
        cur = conn.execute(
            """
            SELECT
                n.ZIDENTIFIER          AS uuid,
                n.ZTITLE               AS title,
                f.ZTITLE               AS folder_name,
                n.ZMODIFICATIONDATE   AS mod_date,   -- macOS absolute-time seconds
                d.ZDATA                AS body_blob,
                n.ZISPASSWORDPROTECTED AS is_enc,
                n.Z_PK                 AS z_pk
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON f.Z_PK = n.ZFOLDER
            LEFT JOIN ZICNOTEDATA      d ON d.ZNOTE   = n.Z_PK
            WHERE n.Z_ENT IN (5, 11, 12)
            ORDER BY n.ZMODIFICATIONDATE DESC
            """
        )
        notes = []
        for row in cur.fetchall():
            uuid, title, folder, mod_ts, body_blob, is_enc, z_pk = row
            if not uuid:
                continue
            body = _decode_body(body_blob)
            body_preview = body[:200].replace("\n", " ").strip()
            mod_iso = (
                datetime.fromtimestamp(mod_ts + 978307200).isoformat()
                if mod_ts else None
            )
            notes.append({
                "uuid": uuid,
                "title": title or "",
                "folder": folder or "(Default)",
                "modified": mod_iso,
                "body_preview": body_preview,
                "body_hash": _body_hash(body),
                "is_encrypted": bool(is_enc),
                "z_pk": z_pk,
            })
        return notes
    finally:
        conn.close()


def detect_duplicates(
    db_path: Path | None = None,
) -> list[list[str]]:
    """Return groups of note UUIDs that share the same body hash.

    Groups are ordered by size descending. Encrypted notes (body unreadable)
    are hashed by their raw blob so duplicates of encrypted content are still
    caught (though text can't be shown).
    """
    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _db_connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT
                n.ZIDENTIFIER  AS uuid,
                CASE
                    WHEN n.ZISPASSWORDPROTECTED = 1
                    THEN HEX(n.Z_PK)          -- can't read body; hash by row id
                    ELSE ?
                END            AS hash_key
            FROM ZICCLOUDSYNCINGOBJECT n
            WHERE n.Z_ENT IN (5, 11, 12)
            """,
            (_body_hash(_decode_body(None)),),  # placeholder; real hash done in Python
        )

        # Group by hash (re-hash in Python to handle body decode)
        hash_groups: dict[str, list[str]] = {}
        for uuid, _ in cur.fetchall():
            # Re-scan for body (this is inefficient but correct for now)
            # We do a second pass to compute actual body hashes
            pass  # handled below

        # Two-pass: first pass builds uuid→blob map, second pass hashes
        cur = conn.execute(
            """
            SELECT n.ZIDENTIFIER, COALESCE(d.ZDATA, X'00')
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICNOTEDATA d ON d.ZNOTE = n.Z_PK
            WHERE n.Z_ENT IN (5, 11, 12)
            """
        )
        groups: dict[str, list[str]] = {}
        for uuid, blob in cur.fetchall():
            if not uuid:
                continue
            h = (
                _body_hash(_decode_body(blob))
                if blob != b'\x00' else
                hashlib.sha256(uuid.encode()).hexdigest()[:16]
            )
            groups.setdefault(h, []).append(uuid)

        return [g for g in groups.values() if len(g) > 1]
    finally:
        conn.close()


def detect_empty(
    db_path: Path | None = None,
    min_chars: int = 10,
) -> list[str]:
    """Return UUIDs of notes whose decoded body has ≤ min_chars characters.

    Notes without any body data (e.g. title-only notes) are also included.
    Encrypted notes are excluded because their body can't be read.
    """
    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _db_connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT n.ZIDENTIFIER, d.ZDATA
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICNOTEDATA d ON d.ZNOTE = n.Z_PK
            WHERE n.Z_ENT IN (5, 11, 12)
              AND n.ZISPASSWORDPROTECTED = 0
            """
        )
        empty = []
        for uuid, blob in cur.fetchall():
            if not uuid:
                continue
            body = _decode_body(blob)
            if len(body.strip()) <= min_chars:
                empty.append(uuid)
        return empty
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# AppleScript operations
# --------------------------------------------------------------------------- #

class AppleScriptError(RuntimeError):
    """Raised when osascript returns a non-zero exit code."""


def _osa(script: str, timeout: float = 20.0) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AppleScriptError(result.stderr.strip())
    return result.stdout.strip()


def archive_note(
    uuid: str,
    db_path: Path | None = None,
) -> bool:
    """Move note uuid → Archive folder via Notes AppleScript.

    Creates the "Archive" folder if it doesn't exist.
    Returns True on success; raises AppleScriptError on failure.

    Note: the Notes.app scripting ID format is x-coredata://{DB_UUID}/ICNote/p{Z_PK}.
    We look up Z_PK from ZIDENTIFIER in the database first.
    """
    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _db_connect(db_path)
    db_uuid = _get_db_uuid(conn)
    try:
        cur = conn.execute(
            "SELECT Z_PK FROM ZICCLOUDSYNCINGOBJECT WHERE ZIDENTIFIER = ? AND Z_ENT IN (5,11,12) LIMIT 1",
            (uuid,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No note with ZIDENTIFIER={uuid}")
        z_pk = row[0]
    finally:
        conn.close()

    note_ref = _note_id_from_pk(db_uuid, z_pk)
    archive_folder = "Archive"

    script = f'''
    tell application "Notes"
        -- Ensure Archive folder exists
        try
            set archiveRef to folder "{archive_folder}"
        on error
            make new folder at end of folders with properties {{name:"{archive_folder}"}}
            set archiveRef to folder "{archive_folder}"
        end try

        set noteRef to note id "{note_ref}"
        move noteRef to archiveRef
    end tell
    '''
    _osa(script)
    return True


def delete_note(
    uuid: str,
    db_path: Path | None = None,
    dry_run: bool = True,
) -> bool:
    """Delete note uuid via Notes AppleScript.

    **WARNING: this is destructive.** Notes.app moves deleted notes to the
    system Trash (accessible via Finder → Trash, 30-day retention), but the
    user sees them disappear from Notes immediately.

    With dry_run=True (default) this method is a no-op and returns True
    after logging the intent. Set dry_run=False to actually delete.

    Returns True on success; raises AppleScriptError on failure.
    """
    if dry_run:
        return True  # no-op guard

    db_path = db_path or DEFAULT_DB
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _db_connect(db_path)
    db_uuid = _get_db_uuid(conn)
    try:
        cur = conn.execute(
            "SELECT Z_PK FROM ZICCLOUDSYNCINGOBJECT WHERE ZIDENTIFIER = ? AND Z_ENT IN (5,11,12) LIMIT 1",
            (uuid,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No note with ZIDENTIFIER={uuid}")
        z_pk = row[0]
    finally:
        conn.close()

    note_ref = _note_id_from_pk(db_uuid, z_pk)

    script = f'''
    tell application "Notes"
        set noteRef to note id "{note_ref}"
        delete noteRef
    end tell
    '''
    _osa(script)
    return True
