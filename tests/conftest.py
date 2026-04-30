"""Pytest configuration and shared fixtures."""
# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Make `scripts/modules` importable without installing as a package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# --------------------------------------------------------------------------- #
# Fake chat.db fixture
# --------------------------------------------------------------------------- #


CHAT_SCHEMA = """
CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    chat_identifier TEXT,
    service_name TEXT,
    display_name TEXT
);

CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    attributedBody BLOB,
    date INTEGER
);

CREATE TABLE chat_message_join (
    chat_id INTEGER,
    message_id INTEGER
);

CREATE TABLE chat_recoverable_message_join (
    chat_id INTEGER,
    message_id INTEGER
);
"""


@pytest.fixture
def fake_chat_db(tmp_path):
    """Create a temporary chat.db-shaped SQLite with sample data.

    Chats included:
    - 10010 (spam — China Unicom prefix)
    - +8618812345678 (normal — Chinese mobile)
    - 95555 (normal — bank short code, default whitelisted)
    - 888888 (unknown — 6-digit short code not in whitelist)
    - 1069876543210 (spam — long numeric id)
    - promo@example.com (unknown — email)
    """
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(CHAT_SCHEMA)

    chats = [
        (1, "iMessage;-;10010", "10010"),
        (2, "iMessage;-;+8618812345678", "+8618812345678"),
        (3, "iMessage;-;95555", "95555"),
        (4, "iMessage;-;888888", "888888"),
        (5, "iMessage;-;1069876543210", "1069876543210"),
        (6, "iMessage;-;promo@example.com", "promo@example.com"),
    ]
    for rowid, guid, cid in chats:
        conn.execute(
            "INSERT INTO chat (ROWID, guid, chat_identifier, service_name) VALUES (?, ?, ?, 'iMessage')",
            (rowid, guid, cid),
        )

    # Add one recent message to each chat
    apple_epoch_ns = 787536000 * 1_000_000_000  # 2026-01-01 ish
    message_samples = {
        1: ("【中国联通】您本月话费 50 元已扣除", None),
        2: ("你好，晚上一起吃饭吗？", None),
        3: ("您尾号1234的卡于01-15消费500元", None),
        4: (None, None),  # unknown
        5: ("【京东】您的订单已发货", None),
        6: ("Get 50% off your next purchase! Click here.", None),
    }
    for rowid, (text, ab) in message_samples.items():
        conn.execute(
            "INSERT INTO message (text, attributedBody, date) VALUES (?, ?, ?)",
            (text, ab, apple_epoch_ns),
        )
        conn.execute(
            "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
            (rowid, rowid),
        )
    conn.commit()
    conn.close()
    return db_path
