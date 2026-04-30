"""Tests for modules.contacts."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from modules import contacts


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class TestNormalizePhone:
    def test_strips_punctuation(self):
        assert contacts._normalize_phone("+86 (138) 1234-5678") == "13812345678"

    def test_strips_86_country_code(self):
        assert contacts._normalize_phone("+8618812345678") == "18812345678"

    def test_strips_1_country_code(self):
        assert contacts._normalize_phone("+14155550100") == "4155550100"

    def test_keeps_unknown_country_code(self):
        # +44 retained because not in our explicit list
        assert contacts._normalize_phone("+442071234567") == "+442071234567"

    def test_empty_returns_empty(self):
        assert contacts._normalize_phone("") == ""
        assert contacts._normalize_phone(None) == ""


class TestNormalizeEmail:
    def test_lowercases_and_strips(self):
        assert contacts._normalize_email("  Foo@Bar.COM  ") == "foo@bar.com"

    def test_empty_returns_empty(self):
        assert contacts._normalize_email("") == ""
        assert contacts._normalize_email(None) == ""


# --------------------------------------------------------------------------- #
# scan_contacts (output parsing)
# --------------------------------------------------------------------------- #


class TestScanContacts:
    def test_parses_rs_us_separators(self):
        RS = "\x1e"
        US = "\x1f"
        fake = (
            f"ID1{US}Alice Chen{US}+8618812345678,{US}alice@example.com,{US}Acme{RS}"
            f"ID2{US}Bob Li{US}{US}bob@example.com,{US}{RS}"
        )
        with patch.object(contacts.common, "osa", return_value=fake):
            result = contacts.scan_contacts()

        assert len(result) == 2
        assert result[0]["id"] == "ID1"
        assert result[0]["full_name"] == "Alice Chen"
        assert result[0]["phones"] == ["+8618812345678"]
        assert result[0]["emails"] == ["alice@example.com"]
        assert result[1]["full_name"] == "Bob Li"
        assert result[1]["phones"] == []

    def test_empty_returns_empty(self):
        with patch.object(contacts.common, "osa", return_value=""):
            assert contacts.scan_contacts() == []


# --------------------------------------------------------------------------- #
# Duplicate detection
# --------------------------------------------------------------------------- #


class TestDetectDuplicatesByPhone:
    def test_finds_matching_phones(self):
        data = [
            {"id": "A", "full_name": "Alice", "phones": ["+86 188 1234 5678"],
             "emails": [], "organization": ""},
            {"id": "B", "full_name": "Alice Chen", "phones": ["18812345678"],
             "emails": [], "organization": ""},
            {"id": "C", "full_name": "Bob", "phones": ["13900000000"],
             "emails": [], "organization": ""},
        ]
        groups = contacts.detect_duplicates_by_phone(data)

        assert len(groups) == 1
        ids = {c["id"] for c in groups[0]}
        assert ids == {"A", "B"}

    def test_ignores_short_normalized_phones(self):
        # "123" is too short (< 7 digits)
        data = [
            {"id": "A", "full_name": "X", "phones": ["123"], "emails": [], "organization": ""},
            {"id": "B", "full_name": "Y", "phones": ["123"], "emails": [], "organization": ""},
        ]
        assert contacts.detect_duplicates_by_phone(data) == []

    def test_unique_phones_produce_no_group(self):
        data = [
            {"id": "A", "full_name": "X", "phones": ["13911111111"], "emails": [], "organization": ""},
            {"id": "B", "full_name": "Y", "phones": ["13922222222"], "emails": [], "organization": ""},
        ]
        assert contacts.detect_duplicates_by_phone(data) == []


class TestDetectDuplicatesByEmail:
    def test_case_insensitive_grouping(self):
        data = [
            {"id": "A", "full_name": "Alice", "phones": [],
             "emails": ["Alice@example.com"], "organization": ""},
            {"id": "B", "full_name": "A C", "phones": [],
             "emails": ["alice@EXAMPLE.com"], "organization": ""},
            {"id": "C", "full_name": "Bob", "phones": [],
             "emails": ["bob@example.com"], "organization": ""},
        ]
        groups = contacts.detect_duplicates_by_email(data)
        assert len(groups) == 1
        assert {c["id"] for c in groups[0]} == {"A", "B"}

    def test_ignores_strings_without_at(self):
        data = [
            {"id": "A", "full_name": "X", "phones": [], "emails": ["notanemail"], "organization": ""},
            {"id": "B", "full_name": "Y", "phones": [], "emails": ["notanemail"], "organization": ""},
        ]
        assert contacts.detect_duplicates_by_email(data) == []


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


class TestExportReport:
    def test_creates_markdown_file(self, tmp_path):
        data = [
            {"id": "A", "full_name": "Alice", "phones": ["13811111111"],
             "emails": ["a@x.com"], "organization": "Co"},
            {"id": "B", "full_name": "A", "phones": ["13811111111"],
             "emails": [], "organization": ""},
        ]
        path = contacts.export_duplicates_report(data, out_dir=tmp_path)
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "Contacts Duplicates Report" in text
        assert "Phone Duplicates" in text
        assert "Email Duplicates" in text
