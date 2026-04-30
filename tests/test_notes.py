"""Tests for scripts/modules/notes.py"""
from __future__ import annotations

import gzip
import hashlib
import sqlite3
from pathlib import Path

import pytest

from modules import notes as notes_module


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _make_body(text: str) -> bytes:
    """Compress text as a gzip blob (mimics NoteStore ZDATA format).

    We embed the text as raw UTF-8 bytes (after a short proto-like prefix)
    so that decode_body() can extract it via errors='ignore' stripping.
    The real NoteStore protobuf embeds UTF-8 text inside a binary proto
    wrapper; our simplified blob does the same by just prepending 20 NUL
    bytes (proto overhead) followed by the UTF-8 text.
    """
    # Simulate proto overhead bytes that get stripped by decode('ignore')
    proto_prefix = b"\x08\x00\x12\x99\x08\x08\x00\x10\x00\x1a\x92\x08\x12\xc4\x03"
    text_bytes = text.encode("utf-8")
    return gzip.compress(proto_prefix + text_bytes)


FAKE_DB_UUID = "TESTDB00-0000-0000-0000-000000000000"

# Pre-built body blobs
_NORMAL_TEXT = "This is a normal note with some content for deduplication testing."
_EMPTY_TEXT = "Hi"  # < 10 chars — treated as empty
_DUP_TEXT = "Duplicate note content — this should be grouped with its twin."

NORMAL_BODY = _make_body(_NORMAL_TEXT)
EMPTY_BODY = _make_body(_EMPTY_TEXT)
DUP_BODY = _make_body(_DUP_TEXT)

NORMAL_HASH = hashlib.sha256(_NORMAL_TEXT.encode()).hexdigest()[:16]
EMPTY_HASH = hashlib.sha256(_EMPTY_TEXT.encode()).hexdigest()[:16]
DUP_HASH = hashlib.sha256(_DUP_TEXT.encode()).hexdigest()[:16]

# Note UUIDs
_UUID_NORMAL = "11111111-1111-1111-1111-111111111111"
_UUID_EMPTY = "22222222-2222-2222-2222-222222222222"
_UUID_DUP_A = "33333333-3333-3333-3333-333333333333"
_UUID_DUP_B = "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def fake_notestore(tmp_path) -> Path:
    """Build a minimal NoteStore.sqlite-shaped DB.

    Schema:
      Z_METADATA         — provides Z_UUID (FAKE_DB_UUID)
      ZICCLOUDSYNCINGOBJECT — notes (Z_ENT IN 5,11,12) + folders (Z_ENT=4)
      ZICNOTEDATA        — body blobs keyed by ZNOTE → ZICCLOUDSYNCINGOBJECT.Z_PK

    Notes:
      - normal note   (Z_ENT=12, readable, body=_NORMAL_TEXT)
      - empty note    (Z_ENT=5,  readable, body=_EMPTY_TEXT, short → empty)
      - dup-a note    (Z_ENT=11, readable, body=_DUP_TEXT, hash matches dup-b)
      - dup-b note    (Z_ENT=5,  readable, body=_DUP_TEXT, hash matches dup-a)

    Folders:
      - Default folder (Z_ENT=4, no title)
      - Archive folder  (Z_ENT=4, title="Archive")
    """
    db_path = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(db_path)
    # Note: do NOT set query_only=ON here — we need to INSERT test data
    conn.executescript("""
    CREATE TABLE ZICCLOUDSYNCINGOBJECT (
        Z_PK          INTEGER PRIMARY KEY,
        Z_ENT         INTEGER,
        Z_OPT         INTEGER,
        ZIDENTIFIER   VARCHAR,
        ZTITLE        VARCHAR,
        ZMODIFICATIONDATE REAL,
        ZISPASSWORDPROTECTED INTEGER DEFAULT 0,
        ZFOLDER       INTEGER
    );
    CREATE TABLE ZICNOTEDATA (
        Z_PK   INTEGER PRIMARY KEY,
        ZNOTE  INTEGER,
        ZDATA  BLOB
    );
    CREATE TABLE Z_METADATA (
        Z_PK   INTEGER PRIMARY KEY,
        Z_UUID VARCHAR
    );
    CREATE INDEX idx_note ON ZICCLOUDSYNCINGOBJECT (Z_ENT);
    CREATE INDEX idx_data_note ON ZICNOTEDATA (ZNOTE);
    """)

    # Z_METADATA
    conn.execute("INSERT INTO Z_METADATA VALUES (1, ?)", (FAKE_DB_UUID,))

    # Folders (Z_ENT=4)
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (1, 4, "folder-default-uuid", None, 1000000000, 0, None),
    )
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (2, 4, "folder-archive-uuid", "Archive", 1000000000, 0, None),
    )

    # Notes: Z_PK 10-13
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (10, 12, _UUID_NORMAL, "Normal Note Title", 1000000000.0, 0, 1),
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (?, ?, ?)", (100, 10, NORMAL_BODY))

    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (11, 5, _UUID_EMPTY, "Empty Note", 1000000010.0, 0, 1),
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (?, ?, ?)", (101, 11, EMPTY_BODY))

    # Encrypted note (Z_ENT=11, ZISPASSWORDPROTECTED=1) — dup-a
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (12, 11, _UUID_DUP_A, "Duplicate A", 1000000020.0, 1, 2),
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (?, ?, ?)", (102, 12, DUP_BODY))

    # dup-b
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
        (13, 5, _UUID_DUP_B, "Duplicate B", 1000000030.0, 0, 2),
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (?, ?, ?)", (103, 13, DUP_BODY))

    conn.commit()
    conn.close()
    return db_path


# --------------------------------------------------------------------------- #
# Decode body helper tests
# --------------------------------------------------------------------------- #

class TestDecodeBody:
    def test_decodes_gzip_utf8_text(self):
        blob = _make_body("Hello World 你好世界")
        result = notes_module._decode_body(blob)
        assert "Hello World" in result
        assert "你好世界" in result

    def test_returns_empty_for_none(self):
        assert notes_module._decode_body(None) == ""

    def test_returns_empty_for_empty_blob(self):
        assert notes_module._decode_body(b"") == ""

    def test_strips_proto_overhead(self):
        # The 15-byte prefix bytes are stripped by errors='ignore'
        blob = _make_body("Actual note content")
        result = notes_module._decode_body(blob)
        assert "Actual note content" in result


# --------------------------------------------------------------------------- #
# list_folders
# --------------------------------------------------------------------------- #

class TestListFolders:
    def test_returns_all_folders(self, fake_notestore):
        folders = notes_module.list_folders(fake_notestore)
        assert len(folders) == 2

    def test_archive_detected(self, fake_notestore):
        folders = notes_module.list_folders(fake_notestore)
        names = {f["name"] for f in folders}
        assert "Archive" in names

    def test_default_folder_named(self, fake_notestore):
        folders = notes_module.list_folders(fake_notestore)
        unnamed = next((f for f in folders if f["name"] == "(Default)"), None)
        assert unnamed is not None

    def test_note_counts(self, fake_notestore):
        folders = notes_module.list_folders(fake_notestore)
        by_name = {f["name"]: f for f in folders}
        # Default folder has 2 notes (normal + empty)
        assert by_name["(Default)"]["note_count"] == 2
        # Archive folder has 2 notes (dup-a + dup-b)
        assert by_name["Archive"]["note_count"] == 2

    def test_raises_on_missing_db(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            notes_module.list_folders(tmp_path / "nonexistent.sqlite")


# --------------------------------------------------------------------------- #
# scan_notes
# --------------------------------------------------------------------------- #

class TestScanNotes:
    def test_returns_all_notes(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        assert len(notes) == 4

    def test_uuid_present(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        uuids = {n["uuid"] for n in notes}
        assert _UUID_NORMAL in uuids
        assert _UUID_EMPTY in uuids

    def test_encrypted_flag(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        by_uuid = {n["uuid"]: n for n in notes}
        # dup-a is Z_ENT=11 with ZISPASSWORDPROTECTED=1
        assert by_uuid[_UUID_DUP_A]["is_encrypted"] is True
        # dup-b is Z_ENT=5 with ZISPASSWORDPROTECTED=0
        assert by_uuid[_UUID_DUP_B]["is_encrypted"] is False

    def test_body_preview_extracted(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        by_uuid = {n["uuid"]: n for n in notes}
        preview = by_uuid[_UUID_NORMAL]["body_preview"]
        # Check key words from the note body are present
        assert "This" in preview
        assert "normal" in preview
        assert "deduplication" in preview
        # Empty note body < 10 chars
        assert by_uuid[_UUID_EMPTY]["body_preview"] in (_EMPTY_TEXT, "")

    def test_body_hash_consistent(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        by_uuid = {n["uuid"]: n for n in notes}
        assert by_uuid[_UUID_DUP_A]["body_hash"] == by_uuid[_UUID_DUP_B]["body_hash"]
        assert by_uuid[_UUID_NORMAL]["body_hash"] != by_uuid[_UUID_EMPTY]["body_hash"]

    def test_modified_iso_timestamp(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        for n in notes:
            assert n["modified"] is not None
            # ISO format check
            assert "T" in n["modified"]

    def test_folder_name(self, fake_notestore):
        notes = notes_module.scan_notes(fake_notestore)
        by_uuid = {n["uuid"]: n for n in notes}
        assert by_uuid[_UUID_NORMAL]["folder"] == "(Default)"
        assert by_uuid[_UUID_DUP_A]["folder"] == "Archive"


# --------------------------------------------------------------------------- #
# detect_duplicates
# --------------------------------------------------------------------------- #

class TestDetectDuplicates:
    def test_finds_duplicate_group(self, fake_notestore):
        groups = notes_module.detect_duplicates(fake_notestore)
        assert len(groups) == 1
        assert set(groups[0]) == {_UUID_DUP_A, _UUID_DUP_B}

    def test_no_duplicates_returns_empty_list(self, tmp_path):
        # Minimal DB with one note
        db = tmp_path / "single.sqlite"
        conn = sqlite3.connect(db)
        conn.executescript("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZIDENTIFIER VARCHAR,
            ZISPASSWORDPROTECTED INTEGER DEFAULT 0
        );
        CREATE TABLE ZICNOTEDATA (Z_PK INTEGER PRIMARY KEY, ZNOTE INTEGER, ZDATA BLOB);
        CREATE TABLE Z_METADATA (Z_PK INTEGER PRIMARY KEY, Z_UUID VARCHAR);
        """)
        conn.execute("INSERT INTO Z_METADATA VALUES (1, ?)", (FAKE_DB_UUID,))
        conn.execute(
            "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?)",
            (1, 5, "solo-uuid", 0),
        )
        conn.execute(
            "INSERT INTO ZICNOTEDATA VALUES (?, ?, ?)",
            (1, 1, _make_body("solo content")),
        )
        conn.commit()
        conn.close()
        groups = notes_module.detect_duplicates(db)
        assert groups == []


# --------------------------------------------------------------------------- #
# detect_empty
# --------------------------------------------------------------------------- #

class TestDetectEmpty:
    def test_finds_short_body_note(self, fake_notestore):
        empty = notes_module.detect_empty(fake_notestore)
        assert _UUID_EMPTY in empty

    def test_excludes_normal_note(self, fake_notestore):
        empty = notes_module.detect_empty(fake_notestore)
        assert _UUID_NORMAL not in empty

    def test_excludes_encrypted_notes(self, fake_notestore):
        # dup-a is encrypted (ZISPASSWORDPROTECTED=1) — should be skipped
        empty = notes_module.detect_empty(fake_notestore)
        assert _UUID_DUP_A not in empty

    def test_respects_min_chars_threshold(self, fake_notestore):
        # _EMPTY_TEXT = "Hi" = 2 chars
        # Default min_chars=10 → "Hi" is empty
        empty_10 = notes_module.detect_empty(fake_notestore, min_chars=10)
        assert _UUID_EMPTY in empty_10
        # min_chars=1 → "Hi" (2) is NOT empty
        empty_1 = notes_module.detect_empty(fake_notestore, min_chars=1)
        assert _UUID_EMPTY not in empty_1


# --------------------------------------------------------------------------- #
# archive_note / delete_note (dry-run guard)
# --------------------------------------------------------------------------- #

class TestArchiveNote:
    def test_raises_on_unknown_uuid(self, fake_notestore):
        with pytest.raises(ValueError, match="No note with ZIDENTIFIER"):
            notes_module.archive_note("not-a-real-uuid", fake_notestore)

    def test_returns_true_for_valid_uuid(self, fake_notestore, monkeypatch):
        # Monkey-patch _osa to avoid actual AppleScript
        called = {}
        def fake_osa(script, timeout=20.0):
            called["script"] = script
            return "ok"
        monkeypatch.setattr(notes_module, "_osa", fake_osa)

        result = notes_module.archive_note(_UUID_NORMAL, fake_notestore)
        assert result is True
        # Verify AppleScript references the correct note ID
        assert FAKE_DB_UUID in called["script"]
        assert "/ICNote/p10" in called["script"]


class TestDeleteNote:
    def test_dry_run_returns_true_without_calling_osa(self, fake_notestore, monkeypatch):
        called = {}
        monkeypatch.setattr(notes_module, "_osa", lambda *a, **k: called.update({"called": True}))
        result = notes_module.delete_note(_UUID_NORMAL, fake_notestore, dry_run=True)
        assert result is True
        assert "called" not in called  # should NOT have called AppleScript

    def test_raises_on_unknown_uuid_even_in_execute_mode(self, fake_notestore):
        with pytest.raises(ValueError, match="No note with ZIDENTIFIER"):
            notes_module.delete_note("not-a-real-uuid", fake_notestore, dry_run=False)
