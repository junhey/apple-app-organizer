"""Tests for modules.common."""
from __future__ import annotations

import re

import pytest

from modules import common


class TestNormalizePhone:
    def test_strips_spaces(self):
        assert common.normalize_phone("+86 187 7391 0065") == "+8618773910065"

    def test_strips_dashes_and_parens(self):
        assert common.normalize_phone("+1 (415) 555-0100") == "+14155550100"

    def test_handles_empty(self):
        assert common.normalize_phone("") == ""


class TestIsProtected:
    def test_cn_mobile_is_protected(self):
        assert common.is_protected("+8618812345678")

    def test_cn_mobile_with_spaces_is_protected(self):
        # Displayed form from Messages UI
        assert common.is_protected("+86 188 1234 5678")

    def test_us_number_is_protected(self):
        assert common.is_protected("+14155550100")

    def test_short_code_not_protected_by_default(self):
        assert not common.is_protected("888888")

    def test_bank_short_code_whitelisted(self):
        assert common.is_protected("95588")  # ICBC

    def test_empty_string_not_protected(self):
        assert not common.is_protected("")

    def test_extra_exact_extends_whitelist(self):
        assert not common.is_protected("12345")
        assert common.is_protected("12345", extra_exact=["12345"])

    def test_extra_pattern_extends_whitelist(self):
        # Use a non-phone identifier so normalize_phone() doesn't strip it
        pat = re.compile(r"^VIP-\w+$")
        assert common.is_protected("VIP-alice", extra_patterns=[pat])


class TestLooksLikeSpam:
    def test_106_prefix_is_spam(self):
        is_spam, reason = common.looks_like_spam("10655001234567", None)
        assert is_spam
        assert "106" in reason

    def test_955_prefix_is_spam(self):
        is_spam, _ = common.looks_like_spam("95599", None)
        # 95599 does NOT start with 955 then? yes it does — 95599 starts with "955"
        assert is_spam

    def test_ad_keyword_in_body_is_spam(self):
        is_spam, reason = common.looks_like_spam("138xxxx", "【京东】限时折扣")
        assert is_spam
        assert "keywords" in reason

    def test_normal_body_not_spam(self):
        is_spam, _ = common.looks_like_spam("+8618812345678", "你好")
        assert not is_spam

    def test_long_numeric_id_is_spam(self):
        # 13-digit id that does NOT match any SPAM_PREFIXES
        is_spam, reason = common.looks_like_spam("7778889990001", None)
        assert is_spam
        assert "numeric sender id" in reason


class TestReportWriters:
    def test_write_json_report_creates_file(self, tmp_path):
        path = common.write_json_report({"a": 1}, tmp_path, prefix="test")
        assert path.exists()
        assert path.suffix == ".json"
        assert path.name.startswith("test-")

    def test_write_markdown_report_creates_file(self, tmp_path):
        rows = [{"chat_id": "10010", "count": 5}]
        path = common.write_markdown_report(
            "Test",
            [("Spam", rows, ["chat_id", "count"])],
            tmp_path,
        )
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "# Test" in content
        assert "10010" in content
        assert "| chat_id | count |" in content

    def test_markdown_report_handles_empty_section(self, tmp_path):
        path = common.write_markdown_report(
            "Empty",
            [("Nothing", [], ["x"])],
            tmp_path,
        )
        assert "_No entries._" in path.read_text(encoding="utf-8")

    def test_markdown_report_truncates_large_sections(self, tmp_path):
        rows = [{"x": i} for i in range(600)]
        path = common.write_markdown_report(
            "Big", [("All", rows, ["x"])], tmp_path,
        )
        content = path.read_text(encoding="utf-8")
        assert "100 more rows truncated" in content  # 600 - 500


class TestOsaTimeout:
    def test_osa_raises_on_failure(self):
        with pytest.raises(common.AppleScriptError):
            common.osa('error "intentional test failure"')
