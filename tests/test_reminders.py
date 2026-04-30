"""Tests for modules.reminders (mocked osascript)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from modules import reminders


# --------------------------------------------------------------------------- #
# list_lists
# --------------------------------------------------------------------------- #


class TestListLists:
    def test_parses_four_column_output(self):
        fake_stdout = (
            "Inbox\t42\t10\t3\n"
            "Work\t20\t5\t0\n"
            "Personal\t8\t2\t1\n"
        )
        with patch.object(reminders.common, "osa", return_value=fake_stdout):
            result = reminders.list_lists()

        assert len(result) == 3
        assert result[0] == {"name": "Inbox", "total": 42, "completed": 10, "overdue": 3}
        assert result[1]["name"] == "Work"
        assert result[2]["overdue"] == 1

    def test_empty_output_returns_empty_list(self):
        with patch.object(reminders.common, "osa", return_value=""):
            assert reminders.list_lists() == []

    def test_skips_malformed_lines(self):
        fake = "good\t1\t2\t3\nbad_line\n"
        with patch.object(reminders.common, "osa", return_value=fake):
            result = reminders.list_lists()
        assert len(result) == 1
        assert result[0]["name"] == "good"


# --------------------------------------------------------------------------- #
# list_completed
# --------------------------------------------------------------------------- #


class TestListCompleted:
    def test_parses_four_columns(self):
        fake = (
            "x-apple-reminderkit://ID1\tBuy milk\t"
            "Monday, March 1, 2026 at 10:00:00 AM\tInbox\n"
            "x-apple-reminderkit://ID2\tPay bill\t"
            "Tuesday, March 2, 2026 at 11:00:00 AM\tPersonal\n"
        )
        with patch.object(reminders.common, "osa", return_value=fake):
            result = reminders.list_completed(older_than_days=7)

        assert len(result) == 2
        assert result[0]["id"] == "x-apple-reminderkit://ID1"
        assert result[0]["name"] == "Buy milk"
        assert result[0]["list"] == "Inbox"

    def test_uses_older_than_days_in_script(self):
        captured = {}

        def capture(script, timeout=60):
            captured["script"] = script
            return ""

        with patch.object(reminders.common, "osa", side_effect=capture):
            reminders.list_completed(older_than_days=42)

        # 42 days * 86400 seconds should appear in the AppleScript
        assert "3628800" in captured["script"]


# --------------------------------------------------------------------------- #
# list_overdue
# --------------------------------------------------------------------------- #


class TestListOverdue:
    def test_parses_overdue_reminders(self):
        fake = "x-apple-reminderkit://ID3\tCall dentist\tFri, Feb 14 2025 10:00:00 AM\tHealth\n"
        with patch.object(reminders.common, "osa", return_value=fake):
            result = reminders.list_overdue()
        assert len(result) == 1
        assert result[0]["name"] == "Call dentist"
        assert result[0]["list"] == "Health"


# --------------------------------------------------------------------------- #
# delete_reminder
# --------------------------------------------------------------------------- #


class TestDeleteReminder:
    def test_dry_run_returns_true_without_calling_osa(self):
        with patch.object(reminders.common, "osa") as mock_osa:
            assert reminders.delete_reminder("ID1", dry_run=True) is True
            mock_osa.assert_not_called()

    def test_execute_calls_osa_and_returns_ok(self):
        with patch.object(reminders.common, "osa", return_value="OK") as mock_osa:
            assert reminders.delete_reminder("ID1", dry_run=False) is True
            mock_osa.assert_called_once()

    def test_execute_returns_false_on_error(self):
        with patch.object(reminders.common, "osa", return_value="ERR:not found"):
            assert reminders.delete_reminder("BOGUS", dry_run=False) is False

    def test_empty_id_returns_false(self):
        assert reminders.delete_reminder("", dry_run=True) is False
        assert reminders.delete_reminder("", dry_run=False) is False


# --------------------------------------------------------------------------- #
# batch_delete_completed
# --------------------------------------------------------------------------- #


class TestBatchDeleteCompleted:
    def test_dry_run_produces_plan_without_deleting(self):
        fake_completed = (
            "ID1\tTask A\tMon Mar 1 2026 10:00:00 AM\tInbox\n"
            "ID2\tTask B\tMon Mar 2 2026 10:00:00 AM\tInbox\n"
        )

        # osa is called twice: once for list_completed, never for delete in dry-run
        with patch.object(reminders.common, "osa", return_value=fake_completed) as mock_osa:
            result = reminders.batch_delete_completed(older_than_days=30, dry_run=True)

        assert result.dry_run is True
        assert result.targeted == ["ID1", "ID2"]
        assert result.deleted == ["ID1", "ID2"]  # delete returned True in dry-run
        # Only the list_completed call happened — delete was a no-op
        assert mock_osa.call_count == 1

    def test_execute_issues_one_osa_call_per_delete(self):
        fake_list_output = "ID1\tTask\tMon Mar 1 2026 10:00:00 AM\tInbox\n"
        osa_calls = []

        def fake_osa(script, timeout=15):
            osa_calls.append(script)
            # First call returns the list; subsequent calls are delete commands returning "OK"
            if "reminders of lst whose completed is true" in script:
                return fake_list_output
            return "OK"

        with patch.object(reminders.common, "osa", side_effect=fake_osa):
            result = reminders.batch_delete_completed(
                older_than_days=30, dry_run=False
            )

        assert result.dry_run is False
        assert result.deleted == ["ID1"]
        # at least 2 osa calls: list + delete
        assert len(osa_calls) >= 2

    def test_on_progress_called_for_each_item(self):
        fake = "A\tX\tdate\tInbox\nB\tY\tdate\tInbox\n"
        progress = []

        with patch.object(reminders.common, "osa", return_value=fake):
            reminders.batch_delete_completed(
                older_than_days=30, dry_run=True,
                on_progress=lambda p: progress.append(p),
            )

        assert len(progress) == 2
        assert progress[0]["total"] == 2
        assert progress[0]["current"]["id"] == "A"


# --------------------------------------------------------------------------- #
# _parse_applescript_date
# --------------------------------------------------------------------------- #


class TestParseDate:
    def test_parses_iso(self):
        dt = reminders._parse_applescript_date("2026-03-07 10:30:00")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 3 and dt.day == 7

    def test_returns_none_for_garbage(self):
        assert reminders._parse_applescript_date("not a date") is None

    def test_returns_none_for_empty(self):
        assert reminders._parse_applescript_date("") is None
