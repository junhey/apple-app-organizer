# NoteStore.sqlite Schema

**Status: placeholder — will be filled during Iteration #2 at 22:30.**

Expected location: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`

Planned contents (Iteration #2):
- `ZICCLOUDSYNCINGOBJECT` table — notes + folders unified
- `ZNOTEDATA` table — BLOB-encoded note payloads
- Key columns: `Z_PK`, `ZTITLE1`, `ZFOLDER`, `ZMODIFICATIONDATE1`, `ZDATA`
- Decoding strategy for `ZDATA` (gzip'd protobuf)
- Encryption detection (`ZISPASSWORDPROTECTED` = 1)
- iCloud vs local folder distinction
