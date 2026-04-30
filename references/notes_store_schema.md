# NoteStore.sqlite Schema

**Source:** `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
**Requires:** Full Disk Access (to read the sandboxed Group Container)

## Key Tables

### `ZICCLOUDSYNCINGOBJECT` — everything is a row here

This is a unified table: notes AND folders share it, distinguished by `Z_ENT`.

| Z_ENT | Meaning | Count (example) |
|-------|---------|----------------|
| 4 | Primary folders (user-created) | 1 |
| 5 | Notes (may have ZTITLE) | 84 |
| 6 | Attachments (images, files) | 151 |
| 7 | Device migration state entries | 12 |
| 11 | Encrypted/password-protected notes | 62 |
| 12 | Normal unencrypted notes | 201 |
| 14 | (unknown — single entry) | 1 |
| 15 | Special system folders (Trash, Default) | 6 |

**Note entities** = `Z_ENT IN (5, 11, 12)`. Real-world note count ≈ Z_ENT=5 + Z_ENT=11 + Z_ENT=12.

#### Key columns for notes (Z_ENT IN (5,11,12))

| Column | Type | Notes |
|--------|------|-------|
| `Z_PK` | INTEGER | Primary key — used in AppleScript note ID: `x-coredata://{DB_UUID}/ICNote/p{Z_PK}` |
| `ZIDENTIFIER` | VARCHAR | UUID (e.g. `D5D6EF1A-8832-4770-B738-6DC6791367A3`) — use this as stable external ID |
| `ZTITLE` | VARCHAR | Note title. May be NULL for body-only notes. |
| `ZSUMMARY` | VARCHAR | Snippet (first line?) — often NULL in practice |
| `ZMODIFICATIONDATE` | TIMESTAMP | macOS absolute-time seconds (add 978307200 for Unix epoch) |
| `ZCREATIONDATE` | TIMESTAMP | Same format |
| `ZISPASSWORDPROTECTED` | INTEGER | 1 = encrypted (body unreadable), 0 = readable |
| `ZFOLDER` | INTEGER | Foreign key → `ZICCLOUDSYNCINGOBJECT.Z_PK` (parent folder) |
| `Z_ENT` | INTEGER | 5/11/12 = note |

#### Key columns for folders (Z_ENT IN (4, 15))

| Column | Type | Notes |
|--------|------|-------|
| `Z_PK` | INTEGER | Primary key — used in AppleScript folder ID: `x-coredata://{DB_UUID}/ICFolder/p{Z_PK}` |
| `ZIDENTIFIER` | VARCHAR | UUID (folder UUID) |
| `ZTITLE` | VARCHAR | Folder name. NULL for the primary default folder. |
| `Z_ENT` | INTEGER | 4 = user folder, 15 = system folder |
| `ZPARENT` | INTEGER | FK to parent folder Z_PK (NULL for top-level) |

### `ZICNOTEDATA` — actual note body content

| Column | Type | Notes |
|--------|------|-------|
| `Z_PK` | INTEGER | Primary key |
| `ZNOTE` | INTEGER | FK → `ZICCLOUDSYNCINGOBJECT.Z_PK` |
| `ZDATA` | BLOB | **The actual note content** — see Decoding below |

### `Z_METADATA` — database identity

| Column | Type | Notes |
|--------|------|-------|
| `Z_UUID` | VARCHAR | The CoreData store UUID needed for AppleScript IDs |

## Decoding `ZDATA` (note body)

`ZDATA` is a **gzip-compressed protobuf** (magic: `1F8B`). Decompress with `gzip.decompress()`.

The decompressed bytes are an **Apple NoteStore protobuf** (nested MessageLite wrappers) with UTF-8 note text interleaved with binary proto fields.

### Simple text extraction (no proto schema needed)

```python
import gzip, re

_TEXT_SEG_RE = re.compile(
    r"[\u4e00-\u9fff]{2,}"   # 2+ consecutive Chinese chars
    r"|[a-zA-Z0-9]{4,}"       # 4+ consecutive ASCII word chars
    r"|[，。！？、：；""''（）【】《》…—·]{2,}",
    re.UNICODE,
)

def decode_body(blob: bytes) -> str:
    raw = gzip.decompress(blob)
    # Decode with errors='ignore' to drop non-UTF-8 proto bytes
    text = raw.decode("utf-8", errors="ignore")
    clean = re.sub(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]", "", text)
    segments = _TEXT_SEG_RE.findall(clean)
    return "\n".join(s.strip() for s in segments if len(s.strip()) >= 2)
```

**Why this works:** The `decode("utf-8", errors="ignore")` call silently drops all bytes that aren't valid UTF-8. Since proto structure bytes (tags, varints) are not valid UTF-8 and the actual Chinese/ASCII text is, this cleanly separates text from structure.

### What the proto structure looks like

The outer MessageLite (NoteStore proto) contains a Note object in field 2 (length-delimited).
The Note's MessageLite contains field 1 (length-delimited) = the actual text content.
Text is UTF-8 encoded. Apple's open-source proto definition: `NoteStore.proto`
(GitHub: `apple-oss-distributions/AppleNotes/NoteStore.proto`).

### AppleScript note ID mapping

```
Z_PK from ZICCLOUDSYNCINGOBJECT
  → x-coredata://{Z_METADATA.Z_UUID}/ICNote/p{Z_PK}
```

Query example:
```sql
SELECT ZIDENTIFIER, ZTITLE, Z_PK
FROM ZICCLOUDSYNCINGOBJECT
WHERE Z_ENT IN (5, 11, 12)
LIMIT 5;
```

## Encryption Detection

`ZISPASSWORDPROTECTED = 1` in `ZICCLOUDSYNCINGOBJECT` means the note is encrypted.
Encrypted notes cannot be read via `ZDATA` — the BLOB is encrypted.
These notes are skipped by `detect_empty()` and `detect_duplicates()` body hash.
Encrypted notes are still included in `scan_notes()` with `is_encrypted: True`
and `body_preview: ""`.

## Folder Query

```sql
-- All folders with note counts
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
ORDER BY f.ZTITLE;
```

## AppleScript Recipes

### Move note to Archive folder
```applescript
tell application "Notes"
    -- Create Archive if missing
    try
        set archiveRef to folder "Archive"
    on error
        make new folder at end of folders with properties {name:"Archive"}
        set archiveRef to folder "Archive"
    end try

    set noteRef to note id "x-coredata://{DB_UUID}/ICNote/p{Z_PK}"
    move noteRef to archiveRef
end tell
```

### Delete note (destructive — goes to system Trash, 30-day retention)
```applescript
tell application "Notes"
    set noteRef to note id "x-coredata://{DB_UUID}/ICNote/p{Z_PK}"
    delete noteRef
end tell
```

## iCloud Sync Lag Warning

Notes changes made via AppleScript (archive, delete) sync to iCloud within ~30 seconds.
If you query the database immediately after an AppleScript action, the change may not
yet be reflected in `NoteStore.sqlite`. Add a `time.sleep(1)` delay before re-scanning.

## Prerequisite Permissions

1. **Full Disk Access** — required to read the Group Container
   ```bash
   sqlite3 -readonly ~/Library/Group\ Containers/group.com.apple.notes/NoteStore.sqlite \
     "SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT IN (5,11,12);"
   ```
2. **Automation permission** — Notes.app must be allowed to control Notes
   (System Settings → Privacy & Security → Automation → Notes)
