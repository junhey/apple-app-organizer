"""Tests for modules.mail."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from modules import mail


# --------------------------------------------------------------------------- #
# scan_mailboxes
# --------------------------------------------------------------------------- #


class TestScanMailboxes:
    def test_parses_four_columns(self):
        fake = (
            "INBOX\tGmail\t2500\t42\n"
            "Sent\tGmail\t1800\t0\n"
            "Junk\tiCloud\t300\t15\n"
        )
        with patch.object(mail.common, "osa", return_value=fake):
            result = mail.scan_mailboxes()

        assert len(result) == 3
        assert result[0] == {"name": "INBOX", "account": "Gmail", "total": 2500, "unread": 42}
        assert result[2]["account"] == "iCloud"

    def test_empty_returns_empty(self):
        with patch.object(mail.common, "osa", return_value=""):
            assert mail.scan_mailboxes() == []


# --------------------------------------------------------------------------- #
# classify_ads
# --------------------------------------------------------------------------- #


class TestClassifyAds:
    def test_matches_keyword_in_subject(self):
        fake = (
            "MID1\t【京东】限时折扣\tsender1@example.com\tMon Jan 1 2026\n"
            "MID2\tLunch today?\tfriend@example.com\tMon Jan 2 2026\n"
            "MID3\tUnsubscribe reminder\tnewsletter@example.com\tMon Jan 3 2026\n"
        )
        with patch.object(mail.common, "osa", return_value=fake):
            result = mail.classify_ads("INBOX", "Gmail")

        ids = {r["id"] for r in result}
        assert "MID1" in ids  # 限时折扣
        assert "MID3" in ids  # unsubscribe
        assert "MID2" not in ids

    def test_matches_keyword_in_sender(self):
        fake = (
            "MID1\tHello\tnewsletter@example.com\tdate\n"
            "MID2\tHello\tfriend@example.com\tdate\n"
        )
        with patch.object(mail.common, "osa", return_value=fake):
            result = mail.classify_ads("INBOX", "Gmail")
        assert len(result) == 1
        assert result[0]["id"] == "MID1"

    def test_custom_keywords(self):
        fake = "MID1\tCOVID update\tinfo@example.com\tdate\n"
        with patch.object(mail.common, "osa", return_value=fake):
            result = mail.classify_ads(
                "INBOX", "Gmail",
                keywords=["covid"],
            )
        assert len(result) == 1

    def test_custom_mailbox_and_account_escaped(self):
        captured = {}

        def capture(script, timeout=120):
            captured["script"] = script
            return ""

        with patch.object(mail.common, "osa", side_effect=capture):
            mail.classify_ads('INBOX"q', 'Gmail"q')

        assert '\\"q' in captured["script"]


# --------------------------------------------------------------------------- #
# move_to_trash
# --------------------------------------------------------------------------- #


class TestMoveToTrash:
    def test_dry_run_does_not_call_osa(self):
        with patch.object(mail.common, "osa") as mock:
            result = mail.move_to_trash(
                ["MID1", "MID2"], "Gmail", "INBOX", dry_run=True,
            )
            mock.assert_not_called()

        assert result.dry_run is True
        assert result.trashed == ["MID1", "MID2"]

    def test_execute_issues_osa_per_message(self):
        calls = []

        def fake(script, timeout=15):
            calls.append(script)
            return "OK"

        with patch.object(mail.common, "osa", side_effect=fake):
            result = mail.move_to_trash(
                ["MID1", "MID2"], "Gmail", "INBOX", dry_run=False,
            )

        assert len(calls) == 2
        assert result.trashed == ["MID1", "MID2"]

    def test_execute_handles_error(self):
        with patch.object(mail.common, "osa", return_value="ERR:NO_TRASH_MAILBOX"):
            result = mail.move_to_trash(
                ["MID1"], "Gmail", "INBOX", dry_run=False,
            )
        assert result.trashed == []
        assert result.failed == [("MID1", "ERR:NO_TRASH_MAILBOX")]

    def test_progress_callback(self):
        progress = []
        with patch.object(mail.common, "osa", return_value="OK"):
            mail.move_to_trash(
                ["A", "B", "C"], "Gmail", "INBOX", dry_run=False,
                on_progress=lambda p: progress.append(p),
            )
        assert len(progress) == 3
        assert progress[2]["index"] == 3


# --------------------------------------------------------------------------- #
# detect_old_unread
# --------------------------------------------------------------------------- #


class TestDetectOldUnread:
    def test_parses_six_columns(self):
        fake = (
            "M1\tOld subject\tsender@example.com\tJan 1 2023\tGmail\tINBOX\n"
            "M2\tAnother\tsender2@example.com\tFeb 1 2023\tGmail\tSocial\n"
        )
        with patch.object(mail.common, "osa", return_value=fake):
            result = mail.detect_old_unread(older_than_months=12)

        assert len(result) == 2
        assert result[0]["id"] == "M1"
        assert result[0]["mailbox"] == "INBOX"
        assert result[1]["mailbox"] == "Social"
