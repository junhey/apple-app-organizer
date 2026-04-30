# Messages chat.db Schema Notes

Located at `~/Library/Messages/chat.db`. Opened **read-only** by this skill:

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

## Key tables

### `chat`

One row per conversation (1:1 or group).

| Column | Notes |
|--------|-------|
| `ROWID` | PK, used in join tables |
| `guid` | Apple iMessage/SMS global id |
| `chat_identifier` | Phone / email / short-code shown in UI |
| `display_name` | Group chat name, NULL for 1:1 |
| `service_name` | `iMessage` or `SMS` |
| `is_archived` | User-archived flag (not the same as delete) |

**Rows remain in `chat` after user deletes a conversation**.

### `message`

| Column | Notes |
|--------|-------|
| `ROWID` | PK |
| `text` | Plain text, often NULL |
| `attributedBody` | NSAttributedString blob — contains real text when `text` is NULL |
| `date` | Nanoseconds since **2001-01-01 UTC** (Apple epoch) |
| `associated_message_type` | 0 = normal; others = tapback/reaction |

### Date conversion

```sql
datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime')
```

### `chat_message_join`

Bridges `chat.ROWID ↔ message.ROWID` (M:N).

### `chat_recoverable_message_join`

**Critical for this skill.** When the user confirms "Delete Conversation",
Messages moves the message-join rows here. Retained 30 days.

```sql
-- How many conversations are pending hard-delete?
SELECT COUNT(DISTINCT chat_id) FROM chat_recoverable_message_join;

-- List them
SELECT DISTINCT c.chat_identifier, COUNT(*) AS pending
FROM chat_recoverable_message_join crmj
JOIN chat c ON c.ROWID = crmj.chat_id
GROUP BY c.chat_identifier
ORDER BY pending DESC;
```

A chat appearing here is what the user sees in **显示 → 最近删除**.

## Deletion semantics

1. User confirms "删除对话"
2. `chat_message_join` rows move to `chat_recoverable_message_join`
3. Chat disappears from sidebar UI
4. `chat` row itself is NOT removed
5. After 30 days (or user clicks delete in Recently Deleted), trigger
   `before_delete_chat_update_sync_chat_deletes` inserts into `sync_deleted_chats`
   and the row is physically removed

**This is why** this skill does not rely on `chat` row count to verify
deletion — it checks UI state (`name of window 1` after advance) instead.

## Useful queries

```sql
-- All chats (includes Recently Deleted)
SELECT COUNT(*) FROM chat;

-- Chats currently visible in sidebar (approximate)
SELECT COUNT(*) FROM chat
WHERE ROWID NOT IN (SELECT DISTINCT chat_id FROM chat_recoverable_message_join);

-- Top senders by message count (useful for spam detection)
SELECT c.chat_identifier, COUNT(m.ROWID) AS msgs
FROM chat c
LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
LEFT JOIN message m ON cmj.message_id = m.ROWID
GROUP BY c.ROWID
ORDER BY msgs DESC
LIMIT 20;
```

## attributedBody decoding

Many messages store text only in `attributedBody` (NSAttributedString blob).
Use the companion `terrylica/cc-skills@imessage-query` skill for full decoding:

```bash
python3 ~/.workbuddy/skills/imessage-query/scripts/decode_attributed_body.py \
    --chat "+862133464992" --limit 1 --order desc
```

That decoder uses a 3-tier strategy (pytypedstream → manual length-prefix → NSString-marker scan).
