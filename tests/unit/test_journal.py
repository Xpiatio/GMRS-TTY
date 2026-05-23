"""Unit tests for gmrs_tty.persistence.journal."""
import json
import os

import pytest

import gmrs_tty.persistence.journal as journal_mod
from gmrs_tty.persistence.journal import delete_journal


@pytest.fixture(autouse=True)
def isolated_journals_dir(tmp_path, monkeypatch):
    """Redirect JOURNALS_DIR to a temp directory for every test."""
    monkeypatch.setattr(journal_mod, "JOURNALS_DIR", str(tmp_path / "journals"))


class TestSaveJournal:
    def test_creates_journals_dir(self):
        journal_mod.save_journal("Title", "Summary", [], "transcript")
        assert os.path.isdir(journal_mod.JOURNALS_DIR)

    def test_file_is_valid_json(self):
        cs = [{"callsign": "WSLZ233", "location": "Denver, CO"}]
        path = journal_mod.save_journal("T", "S", cs, "text")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["title"] == "T"
        assert data["summary"] == "S"
        assert data["callsigns"] == ["WSLZ233"]
        assert data["callsigns_locations"] == cs
        assert data["transcript"] == "text"
        assert "exported_at" in data

    def test_filename_uses_timestamp_format(self):
        path = journal_mod.save_journal("T", "S", [], "")
        name = os.path.basename(path)
        assert name.endswith(".json")
        # YYYYMMDD_HHMMSS.json — 20 chars including extension
        assert len(name) == 20

    def test_returns_path_to_new_file(self):
        path = journal_mod.save_journal("T", "S", [], "")
        assert os.path.isfile(path)

    def test_multiple_saves_create_distinct_files(self, monkeypatch):
        import datetime

        times = [
            datetime.datetime(2026, 1, 1, 12, 0, 0),
            datetime.datetime(2026, 1, 1, 12, 0, 1),
        ]
        call_count = 0

        class _FakeDatetime(datetime.datetime):
            @classmethod
            def now(cls):
                nonlocal call_count
                t = times[call_count]
                call_count += 1
                return t

        monkeypatch.setattr(journal_mod, "datetime", _FakeDatetime)
        p1 = journal_mod.save_journal("A", "A", [], "")
        p2 = journal_mod.save_journal("B", "B", [], "")
        assert p1 != p2


class TestLoadJournals:
    def test_returns_empty_list_when_dir_missing(self):
        assert journal_mod.load_journals() == []

    def test_returns_entries_newest_first(self):
        journal_mod.save_journal("First", "S", [], "")
        import time; time.sleep(0.01)  # noqa: E401  ensure distinct mtime/name
        # Write a second file with a later timestamp by manipulating the name
        later_path = os.path.join(
            journal_mod.JOURNALS_DIR, "20260101_120001.json"
        )
        earlier_path = os.path.join(
            journal_mod.JOURNALS_DIR, "20260101_120000.json"
        )
        os.makedirs(journal_mod.JOURNALS_DIR, exist_ok=True)
        for path, title in ((later_path, "Later"), (earlier_path, "Earlier")):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"title": title, "exported_at": path, "callsigns": [], "summary": "", "transcript": ""}, fh)

        entries = journal_mod.load_journals()
        titles = [e["title"] for e in entries]
        assert titles.index("Later") < titles.index("Earlier")

    def test_skips_corrupt_files(self):
        os.makedirs(journal_mod.JOURNALS_DIR, exist_ok=True)
        bad = os.path.join(journal_mod.JOURNALS_DIR, "20260101_000000.json")
        with open(bad, "w") as fh:
            fh.write("not json{{{")
        good_path = journal_mod.save_journal("Good", "S", [], "")
        entries = journal_mod.load_journals()
        assert len(entries) == 1
        assert entries[0]["title"] == "Good"

    def test_each_entry_includes_file_path(self):
        path = journal_mod.save_journal("T", "S", [], "")
        entries = journal_mod.load_journals()
        assert entries[0]["_file"] == path

    def test_ignores_non_json_files(self):
        os.makedirs(journal_mod.JOURNALS_DIR, exist_ok=True)
        txt = os.path.join(journal_mod.JOURNALS_DIR, "readme.txt")
        with open(txt, "w") as fh:
            fh.write("ignore me")
        assert journal_mod.load_journals() == []


class TestDeleteJournal:
    def test_removes_file(self):
        path = journal_mod.save_journal("T", "S", [], "")
        assert os.path.isfile(path)
        delete_journal(path)
        assert not os.path.isfile(path)

    def test_deleted_entry_absent_from_load(self):
        path = journal_mod.save_journal("T", "S", [], "")
        delete_journal(path)
        assert journal_mod.load_journals() == []

    def test_raises_on_missing_file(self):
        with pytest.raises(OSError):
            delete_journal(os.path.join(journal_mod.JOURNALS_DIR, "nonexistent.json"))
