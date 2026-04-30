"""Tests for modules.calendar (mocked osascript)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from modules import calendar as cal_module


# --------------------------------------------------------------------------- #
# list_calendars
# --------------------------------------------------------------------------- #


class TestListCalendars:
    def test_parses_three_column_output(self):
        fake = (
            "Work\t65535, 0, 0\t142\n"
            "Home\t0, 65535, 0\t58\n"
        )
        with patch.object(cal_module.common, "osa", return_value=fake):
            result = cal_module.list_calendars()

        assert len(result) == 2
        assert result[0] == {"name": "Work", "color": "65535, 0, 0", "event_count": 142}
        assert result[1]["event_count"] == 58

    def test_empty_returns_empty(self):
        with patch.object(cal_module.common, "osa", return_value=""):
            assert cal_module.list_calendars() == []


# --------------------------------------------------------------------------- #
# list_past_events
# --------------------------------------------------------------------------- #


class TestListPastEvents:
    def test_parses_event_tuple(self):
        fake = (
            "UID-1\tSprint planning\t2024-01-15 10:00:00\tWork\n"
            "UID-2\tLunch\t2024-02-20 12:00:00\tPersonal\n"
        )
        with patch.object(cal_module.common, "osa", return_value=fake):
            result = cal_module.list_past_events(older_than_months=6)

        assert len(result) == 2
        assert result[0]["id"] == "UID-1"
        assert result[0]["summary"] == "Sprint planning"
        assert result[0]["calendar"] == "Work"

    def test_excludes_whitelist_calendars(self):
        fake = (
            "UID-1\tEvent A\t2024-01-01\tWork\n"
            "UID-2\tEvent B\t2024-01-01\tBirthdays\n"
            "UID-3\tEvent C\t2024-01-01\tWork\n"
        )
        with patch.object(cal_module.common, "osa", return_value=fake):
            result = cal_module.list_past_events(
                older_than_months=6,
                exclude_calendars=["Birthdays"],
            )

        cal_names = [e["calendar"] for e in result]
        assert "Birthdays" not in cal_names
        assert cal_names.count("Work") == 2

    def test_uses_months_in_script(self):
        captured = {}

        def capture(script, timeout=120):
            captured["script"] = script
            return ""

        with patch.object(cal_module.common, "osa", side_effect=capture):
            cal_module.list_past_events(older_than_months=24)

        # 24 months * 30 days = 720
        assert "720" in captured["script"]


# --------------------------------------------------------------------------- #
# delete_event
# --------------------------------------------------------------------------- #


class TestDeleteEvent:
    def test_dry_run_skips_osa(self):
        with patch.object(cal_module.common, "osa") as mock:
            assert cal_module.delete_event("UID", "Work", dry_run=True) is True
            mock.assert_not_called()

    def test_execute_returns_true_on_ok(self):
        with patch.object(cal_module.common, "osa", return_value="OK"):
            assert cal_module.delete_event("UID", "Work", dry_run=False) is True

    def test_execute_returns_false_on_error(self):
        with patch.object(cal_module.common, "osa", return_value="ERR:not found"):
            assert cal_module.delete_event("UID", "Work", dry_run=False) is False

    def test_empty_inputs_return_false(self):
        assert cal_module.delete_event("", "Work", dry_run=True) is False
        assert cal_module.delete_event("UID", "", dry_run=True) is False

    def test_quotes_in_inputs_are_escaped(self):
        captured = {}

        def capture(script, timeout=15):
            captured["script"] = script
            return "OK"

        with patch.object(cal_module.common, "osa", side_effect=capture):
            cal_module.delete_event('U"ID', 'Cal"Name', dry_run=False)

        # Both quotes should be escaped
        assert '\\"' in captured["script"]


# --------------------------------------------------------------------------- #
# detect_recurring_duplicates
# --------------------------------------------------------------------------- #


class TestDetectRecurringDuplicates:
    def test_groups_events_with_identical_summary_and_start(self):
        events = [
            {"id": "A", "summary": "Standup", "start_date": "2026-03-01", "calendar": "Work"},
            {"id": "B", "summary": "Standup", "start_date": "2026-03-01", "calendar": "Work"},
            {"id": "C", "summary": "Lunch", "start_date": "2026-03-01", "calendar": "Home"},
        ]
        groups = cal_module.detect_recurring_duplicates(events)

        assert len(groups) == 1
        assert {e["id"] for e in groups[0]} == {"A", "B"}

    def test_unique_events_produce_no_groups(self):
        events = [
            {"id": "A", "summary": "A", "start_date": "2026-01-01", "calendar": "Work"},
            {"id": "B", "summary": "B", "start_date": "2026-02-01", "calendar": "Work"},
        ]
        assert cal_module.detect_recurring_duplicates(events) == []


# --------------------------------------------------------------------------- #
# purge_past
# --------------------------------------------------------------------------- #


class TestPurgePast:
    def test_dry_run_collects_plan_without_deleting(self):
        fake = (
            "UID-1\tOld event\t2020-01-01\tArchive\n"
            "UID-2\tOther\t2019-01-01\tArchive\n"
        )
        with patch.object(cal_module.common, "osa", return_value=fake) as mock_osa:
            result = cal_module.purge_past(
                older_than_months=12,
                whitelist_calendars=[],
                dry_run=True,
            )

        assert result.dry_run is True
        assert len(result.targeted) == 2
        assert result.deleted == ["UID-1", "UID-2"]
        # Only list call; no delete called (dry_run True)
        assert mock_osa.call_count == 1

    def test_whitelist_skips_calendars(self):
        fake = (
            "UID-1\tWork event\t2024-01-01\tWork\n"
            "UID-2\tBday\t2024-01-01\tBirthdays\n"
        )
        # Two osa paths possible: list (returns 2 rows), then possibly delete
        # We want Birthdays filtered out BEFORE any delete
        with patch.object(cal_module.common, "osa", return_value=fake) as mock_osa:
            result = cal_module.purge_past(
                older_than_months=12,
                whitelist_calendars=["Birthdays"],
                dry_run=True,
            )

        # Birthdays filtered at list_past_events level (exclude_calendars)
        ids = [e["id"] for e in result.targeted]
        assert "UID-2" not in ids

    def test_on_progress_invoked_per_event(self):
        fake = (
            "UID-1\tA\t2024-01-01\tWork\n"
            "UID-2\tB\t2024-01-01\tWork\n"
        )
        progress = []
        with patch.object(cal_module.common, "osa", return_value=fake):
            cal_module.purge_past(
                older_than_months=12,
                dry_run=True,
                on_progress=lambda p: progress.append(p),
            )
        assert len(progress) == 2
        assert progress[1]["index"] == 2
        assert progress[1]["total"] == 2
