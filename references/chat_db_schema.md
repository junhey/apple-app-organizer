# chat.db Schema Notes

The macOS iMessage database lives at `~/Library/Messages/chat.db`. Key tables used by this skill:

## `chat`

One row per conversation (1:1 or group).

| Column | Meaning |
|--------|---------|
| `ROWID` | Primary key, referenced by join tables |
| `guid` | Apple iMessage/SMS global identifier |
| `chat_identifier` | Phone number, email, or short code — displayed in UI |
| `display_name` | Group chat name, usually NULL for 1:1 |
| `service_name` | `iMessage` \| `SMS` |
| `is_archived` | 1 if user archived (not used by "delete") |
| `is_recovered` | Not set when recently-deleted — use `chat_recoverable_message_join` instead |

**CRITICAL**: Rows remain in `chat` even after the user deletes a conversation. The "Recently Deleted" folder is represented by a separate join table, NOT a status flag on `chat`.

## `message`

One row per individual message.

| Column | Meaning |
|--------|---------|
| `ROWID` | Primary key |
| `text` | Plain-text body, often NULL |
| `attributedBody` | NSAttributedString binary blob — contains the real text when `text` is NULL |
| `date` | Nanoseconds since 2001-01-01 UTC (Apple epoch) |
| `cache_has_attachments` | 1 if the message has an image/file |
| `associated_message_type` | 0 = normal, else = tapback/reaction |

### Date conversion

```sql
datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime') AS iso_time
```

### Text extraction strategy

1. Read `m.text`. If non-empty, use it.
2. Otherwise, `m.attributedBody` is likely populated. Decode via:
   - Tier 1: `pytypedstream` Unarchiver (proper typedstream deserialization)
   - Tier 2: Length-prefix parsing (NSString markers 0x2B/0x4F/0x49)
   - Tier 3: Raw byte scan for NSString marker + length-prefix
3. Use the companion `imessage-query` skill (https://skills.sh/terrylica/cc-skills/imessage-query) which implements all three tiers.

## `chat_message_join`

Bridges `chat.ROWID <-> message.ROWID` (M:N). Every normal message links here.

## `chat_recoverable_message_join`

**Key for this skill.** Messages in the "Recently Deleted" folder move from `chat_message_join` to here. Retained for 30 days.

```sql
-- Count conversations with recoverable messages (i.e., pending permanent delete)
SELECT COUNT(DISTINCT chat_id) FROM chat_recoverable_message_join;

-- List those chats
SELECT DISTINCT c.chat_identifier, COUNT(*) AS pending
FROM chat_recoverable_message_join crmj
JOIN chat c ON c.ROWID = crmj.chat_id
GROUP BY c.chat_identifier
ORDER BY pending DESC;
```

A chat appearing here is what the user sees in **显示 → 最近删除**.

## Deletion semantics

When the user selects **对话 → 删除对话…** and confirms:

1. Rows in `chat_message_join` for that chat move to `chat_recoverable_message_join`
2. The chat disappears from the main sidebar
3. `chat` row is NOT removed
4. After 30 days (or when user clicks "删除" in Recently Deleted), trigger
   `before_delete_chat_update_sync_chat_deletes` inserts into `sync_deleted_chats`
   and the row is physically removed

This is why the batch-delete script relies on UI state (sidebar contents via `name of window 1`) rather than querying `chat`.

## Useful queries

```sql
-- Total chats (includes Recently Deleted but not fully purged)
SELECT COUNT(*) FROM chat;

-- Chats currently shown in sidebar (approximation)
SELECT COUNT(*) FROM chat
WHERE ROWID NOT IN (SELECT DISTINCT chat_id FROM chat_recoverable_message_join);

-- Top senders by message count
SELECT c.chat_identifier, COUNT(m.ROWID) AS msgs
FROM chat c
LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
LEFT JOIN message m ON cmj.message_id = m.ROWID
GROUP BY c.ROWID
ORDER BY msgs DESC
LIMIT 20;
```
