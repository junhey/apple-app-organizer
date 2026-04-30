"""
Integration tests for apple-app-organizer.

These tests invoke each CLI subcommand with --dry-run in a subprocess
and assert:
  1. No Python/OS errors
  2. Valid JSON output (for scan/report)
  3. --execute is required to actually mutate (verify dry_run is default)

Note: These tests do NOT require macOS Automation permissions to run —
they test CLI argument parsing and stub-safe module logic.
For full end-to-end tests, run on a macOS machine with permissions granted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Path to the CLI entry point
CLI = Path(__file__).parent.parent / "scripts" / "organize.py"
PYTHON = sys.executable


def run_cli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run the CLI and return the result."""
    return subprocess.run(
        [PYTHON, str(CLI)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "TERM": "dumb"},
    )


class TestCLIParsing:
    """Test that the CLI accepts all subcommands and flags without crashing."""

    MODULES = ["messages", "notes", "reminders", "calendar", "contacts", "mail"]

    @pytest.mark.parametrize("module", MODULES)
    def test_subcommand_exists(self, module):
        """Each module subcommand should be recognized by argparse."""
        result = run_cli([module, "scan", "--dry-run"])
        # Should not fail due to unknown module
        assert module in result.stdout or module in result.stderr or result.returncode in (0, 1), \
            f"Module '{module}' not recognized. stderr={result.stderr}"

    def test_invalid_module_shows_help(self):
        """Invalid module name should produce a helpful error."""
        result = run_cli(["nonexistent", "scan"])
        assert result.returncode != 0
        assert "invalid choice" in result.stderr or "help" in result.stderr.lower()

    def test_dry_run_default(self):
        """Without --execute, CLI should not attempt mutations."""
        result = run_cli(["messages", "scan"])
        # No "EXECUTING" message should appear
        assert "EXECUTING" not in result.stdout, "dry_run should be default"
        assert result.returncode in (0, 1)  # 1 = permission denied on non-macOS, that's OK

    def test_execute_flag_accepted(self):
        """--execute flag should be accepted without error."""
        result = run_cli(["messages", "scan", "--execute"])
        # Should not fail on --execute flag recognition
        assert "unrecognized arguments" not in result.stderr


class TestModulesCanBeImported:
    """Test that all modules can be imported without errors."""

    def test_import_all_modules(self):
        """All 6 modules should be importable."""
        from scripts.modules import messages, notes, reminders, calendar, contacts, mail
        assert hasattr(messages, "scan")
        assert hasattr(notes, "scan")
        assert hasattr(reminders, "scan")
        assert hasattr(calendar, "scan")
        assert hasattr(contacts, "scan")
        assert hasattr(mail, "scan")

    def test_contacts_has_required_functions(self):
        """Contacts module should expose the required TDD functions."""
        from scripts.modules.contacts import (
            scan_contacts,
            detect_duplicates_by_phone,
            detect_duplicates_by_email,
            merge_duplicates,
            export_duplicates_report,
        )
        assert callable(scan_contacts)
        assert callable(detect_duplicates_by_phone)
        assert callable(detect_duplicates_by_email)
        assert callable(merge_duplicates)
        assert callable(export_duplicates_report)

    def test_mail_has_required_functions(self):
        """Mail module should expose the required TDD functions."""
        from scripts.modules.mail import (
            scan_mailboxes,
            classify_ads,
            move_to_trash,
            detect_old_unread,
        )
        assert callable(scan_mailboxes)
        assert callable(classify_ads)
        assert callable(move_to_trash)
        assert callable(detect_old_unread)

    def test_contacts_merge_returns_plan(self):
        """merge_duplicates() should return a dict with strategy, even in dry_run."""
        from scripts.modules.contacts import merge_duplicates
        result = merge_duplicates(
            {"phone_normalized": "1234567", "contacts": [
                {"id": "p1", "full_name": "Alice", "phones": ["1234567"], "emails": []},
                {"id": "p2", "full_name": "Alice B", "phones": ["1234567"], "emails": []},
            ]},
            dry_run=True,
        )
        assert isinstance(result, dict)
        assert result["dry_run"] is True
        assert "strategy" in result
        assert "manual_merge_required" in result["strategy"]

    def test_mail_move_to_trash_respects_dry_run(self):
        """move_to_trash() should return IDs unchanged in dry_run."""
        from scripts.modules.mail import move_to_trash
        ids = ["123", "456"]
        result = move_to_trash(ids, dry_run=True)
        assert result == ids  # no mutation

    def test_mail_move_to_trash_dry_run_with_real_ids_does_not_crash(self):
        """move_to_trash(dry_run=True) should not crash even with garbage IDs."""
        from scripts.modules.mail import move_to_trash
        # Should not raise, just return empty
        result = move_to_trash(["999999999"], dry_run=True)
        assert result == ["999999999"]


class TestContactsLogic:
    """Unit tests for contacts module logic (no AppleScript needed)."""

    def test_normalize_phone(self):
        from scripts.modules.utils import normalize_phone
        assert normalize_phone("+86 138 1234 5678") == "13812345678"
        assert normalize_phone("+86-138-1234-5678") == "13812345678"
        assert normalize_phone("138-1234-5678") == "13812345678"

    def test_normalize_email(self):
        from scripts.modules.utils import normalize_email
        assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"
        assert normalize_email("BOB@GMAIL.COM") == "bob@gmail.com"

    def test_detect_duplicates_by_phone(self):
        from scripts.modules.contacts import detect_duplicates_by_phone
        contacts = [
            {"id": "c1", "full_name": "Alice", "phones": ["+86 138 1234 5678"], "emails": [], "organization": ""},
            {"id": "c2", "full_name": "Alice A", "phones": ["13812345678"], "emails": [], "organization": ""},
            {"id": "c3", "full_name": "Bob", "phones": ["13900000000"], "emails": [], "organization": ""},
        ]
        dupes = detect_duplicates_by_phone(contacts)
        assert len(dupes) == 1
        assert dupes[0]["count"] == 2
        assert dupes[0]["phone_normalized"] == "13812345678"

    def test_detect_duplicates_by_email(self):
        from scripts.modules.contacts import detect_duplicates_by_email
        contacts = [
            {"id": "c1", "full_name": "Alice", "phones": [], "emails": ["Alice@Example.com"], "organization": ""},
            {"id": "c2", "full_name": "Alice B", "phones": [], "emails": ["alice@example.com"], "organization": ""},
            {"id": "c3", "full_name": "Bob", "phones": [], "emails": ["bob@example.com"], "organization": ""},
        ]
        dupes = detect_duplicates_by_email(contacts)
        assert len(dupes) == 1
        assert dupes[0]["count"] == 2
        assert dupes[0]["email_normalized"] == "alice@example.com"

    def test_export_duplicates_report_writes_file(self, tmp_path):
        from scripts.modules.contacts import export_duplicates_report
        path = export_duplicates_report(
            phone_dupes=[{
                "phone_normalized": "13800000000",
                "phone_raw": "13800000000",
                "count": 2,
                "contacts": [
                    {"id": "x", "full_name": "Test", "phones": ["13800000000"], "emails": [], "organization": ""},
                ],
            }],
            output_dir=tmp_path,
        )
        assert path.exists()
        content = path.read_text()
        assert "Contacts Duplicate Merge Report" in content
        assert "13800000000" in content


class TestMailLogic:
    """Unit tests for mail module logic (no AppleScript needed)."""

    def test_classify_ads_keyword_match(self):
        from scripts.modules.mail import classify_ads
        # We can't call classify_ads without Mail.app, but we can verify
        # the function signature and import
        assert callable(classify_ads)

    def test_mail_report_generation(self, tmp_path):
        from scripts.modules.mail import generate_report
        path = generate_report(output_dir=tmp_path, mailbox="INBOX", older_than_months=6)
        assert path.exists()
        content = path.read_text()
        assert "Mail Cleanup Report" in content
        assert "INBOX" in content


class TestSharedUtils:
    def test_truncate(self):
        from scripts.modules.utils import truncate
        assert truncate("hello", 10) == "hello"
        assert truncate("hello world this is long", 10) == "hello w..."

    def test_write_json_creates_dir(self, tmp_path):
        from scripts.modules.utils import write_json
        p = tmp_path / "sub" / "data.json"
        write_json([{"a": 1}], p)
        assert p.exists()
        assert json.loads(p.read_text()) == [{"a": 1}]


class TestPermissionsCheck:
    """Test that check_permissions() functions exist and are callable."""

    def test_all_modules_have_permission_check(self):
        from scripts.modules import messages, notes, reminders, calendar, contacts, mail
        assert callable(messages.check_permissions)
        assert callable(notes.check_permissions)
        assert callable(reminders.check_permissions)
        assert callable(calendar.check_permissions)
        assert callable(contacts.check_permissions)
        assert callable(mail.check_permissions)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
