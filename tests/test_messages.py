"""Tests for modules.messages (scan + classify)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from modules import messages


class TestClassify:
    def test_real_mobile_is_normal(self):
        label, _ = messages.classify("+8618812345678", "你好")
        assert label == "normal"

    def test_10010_is_spam(self):
        label, reason = messages.classify("10010", None)
        assert label == "spam"
        assert "106" in reason or "10010" in reason

    def test_long_numeric_is_spam(self):
        label, _ = messages.classify("10691781103459", None)
        assert label == "spam"

    def test_bank_short_code_is_normal(self):
        # 95555 (招商银行) is in the default whitelist
        label, reason = messages.classify("95555", "您尾号消费500元")
        assert label == "normal"
        assert "whitelist" in reason

    def test_4_digit_short_code_is_unknown(self):
        label, _ = messages.classify("8888", None)
        assert label == "unknown"

    def test_email_is_unknown(self):
        label, reason = messages.classify("promo@example.com", None)
        assert label == "unknown"
        assert "email" in reason

    def test_ad_keyword_overrides_mobile_detection(self):
        # Short non-mobile id + spam keyword
        label, _ = messages.classify("9999999999", "【京东】限时折扣")
        assert label == "spam"


class TestScan:
    def test_scan_classifies_fake_db(self, fake_chat_db):
        result = messages.scan(fake_chat_db)
        assert set(result.keys()) == {"spam", "normal", "unknown"}

        spam_ids = {c["chat_id"] for c in result["spam"]}
        normal_ids = {c["chat_id"] for c in result["normal"]}
        unknown_ids = {c["chat_id"] for c in result["unknown"]}

        assert "10010" in spam_ids
        assert "1069876543210" in spam_ids
        assert "+8618812345678" in normal_ids
        assert "95555" in normal_ids
        assert "888888" in unknown_ids
        assert "promo@example.com" in unknown_ids

    def test_scan_includes_last_text(self, fake_chat_db):
        result = messages.scan(fake_chat_db)
        entry = next(c for c in result["spam"] if c["chat_id"] == "10010")
        assert "话费" in (entry["last_text"] or "")

    def test_scan_missing_db_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            messages.scan(tmp_path / "nonexistent.db")


class TestBatchDeleteDryRun:
    """batch_delete in dry-run mode — no osascript should actually delete."""

    def test_dry_run_respects_whitelist(self):
        # Simulate window cycle: protected -> target -> empty
        sequence = iter([
            "+86 188 1234 5678",  # protected (whitelist)
            "+86 188 1234 5678",  # still protected (after sheet clear)
            "10010",              # target
            "10010",              # still target (after switch to next fails... actually it's new)
            "",                   # empty — loop ends
        ])

        def fake_name():
            return next(sequence, "")

        calls = []

        def fake_switch(direction):
            calls.append(("switch", direction))
            return next(sequence, "")

        def fake_delete():
            calls.append(("delete",))
            return True, ""

        with patch.object(messages, "_current_window_name", side_effect=fake_name), \
             patch.object(messages, "_clear_pending_sheet", return_value=False), \
             patch.object(messages, "_switch", side_effect=fake_switch), \
             patch.object(messages, "_delete_current_chat", side_effect=fake_delete):
            result = messages.batch_delete(
                ["10010"],
                dry_run=True,
                max_iterations=10,
            )

        # In dry-run we should NEVER have called the real delete
        assert ("delete",) not in calls
        # But 10010 should be recorded as would-be deleted
        assert "10010" in result.deleted

    def test_loop_detection_halts(self):
        def fake_name():
            return "stuck_id_12345"

        with patch.object(messages, "_current_window_name", side_effect=fake_name), \
             patch.object(messages, "_clear_pending_sheet", return_value=False), \
             patch.object(messages, "_switch", return_value="stuck_id_12345"), \
             patch.object(messages, "_delete_current_chat", return_value=(True, "")):
            result = messages.batch_delete(
                ["stuck_id_12345"],
                dry_run=True,
                max_iterations=20,
            )

        # Loop detection should engage before 20 iterations
        assert result.halted_on == "stuck_id_12345"
        assert result.error == "stuck_on_same_chat"

    def test_uncertain_chat_halts_instead_of_deletes(self):
        """If current chat is neither in delete list nor inline-spam, must halt."""
        sequence = iter(["some_random_unknown_id", ""])

        with patch.object(messages, "_current_window_name", side_effect=lambda: next(sequence, "")), \
             patch.object(messages, "_clear_pending_sheet", return_value=False), \
             patch.object(messages, "_switch", return_value=""), \
             patch.object(messages, "_delete_current_chat", return_value=(True, "")):
            result = messages.batch_delete(
                ["unrelated_chat"],
                dry_run=True,
                max_iterations=5,
            )

        assert result.halted_on == "some_random_unknown_id"
        assert result.error == "uncertain_chat_requires_review"
        assert "some_random_unknown_id" not in result.deleted
