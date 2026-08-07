"""Net session store — save/load/delete round-trips and path-traversal guard."""
import json

import pytest

from gmrs_tty.persistence.net_sessions import (
    _iso,
    delete_session,
    load_session,
    load_session_summaries,
    normalize_roster,
    save_session,
)

ROSTER = [
    {"callsign": "wslz233", "name": " Ben ", "location": "Ada, MI",
     "gmrs": "wslz233", "ham": "ke8aaa"},
    {"callsign": "WRAA111", "name": "", "location": "", "gmrs": "", "ham": ""},
]


class TestIso:
    def test_unix_timestamp(self):
        assert _iso(0) == "1970-01-01T00:00:00+00:00"

    def test_z_suffix_normalized(self):
        assert _iso("2026-08-07T12:00:00Z") == "2026-08-07T12:00:00+00:00"

    def test_blank_and_garbage_pass_through(self):
        assert _iso("") == ""
        assert _iso("not-a-date") == "not-a-date"


class TestNormalizeRoster:
    def test_uppercases_and_strips(self):
        rows = normalize_roster(ROSTER)
        assert rows[0] == {
            "callsign": "WSLZ233", "name": "Ben", "location": "Ada, MI",
            "gmrs": "WSLZ233", "ham": "KE8AAA",
        }

    def test_missing_fields_become_blank(self):
        assert normalize_roster([{}]) == [{
            "callsign": "", "name": "", "location": "", "gmrs": "", "ham": "",
        }]


class TestSaveLoadDelete:
    def test_round_trip(self, tmp_path):
        path = save_session(0, 600, 600, ROSTER, sessions_dir=tmp_path)
        stored = json.loads(open(path).read())
        assert stored["duration_seconds"] == 600
        assert stored["roster"][0]["callsign"] == "WSLZ233"

        summaries = load_session_summaries(tmp_path)
        assert len(summaries) == 1
        assert summaries[0]["checkin_count"] == 2
        assert summaries[0]["stations"][0] == {"callsign": "WSLZ233", "name": "Ben"}

        full = load_session(summaries[0]["id"], tmp_path)
        assert full["roster"][1]["callsign"] == "WRAA111"

        delete_session(summaries[0]["id"], tmp_path)
        assert load_session_summaries(tmp_path) == []

    def test_summaries_newest_first(self, tmp_path):
        (tmp_path / "20260101_000000.json").write_text(
            json.dumps({"id": "20260101_000000", "roster": []})
        )
        (tmp_path / "20260201_000000.json").write_text(
            json.dumps({"id": "20260201_000000", "roster": []})
        )
        ids = [s["id"] for s in load_session_summaries(tmp_path)]
        assert ids == ["20260201_000000", "20260101_000000"]

    def test_unreadable_file_skipped(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not json")
        assert load_session_summaries(tmp_path) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_session_summaries(tmp_path / "nope") == []


class TestPathTraversalGuard:
    def test_slash_in_id_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            delete_session("../evil", tmp_path)
        with pytest.raises(ValueError):
            delete_session("a/b", tmp_path)
        with pytest.raises(ValueError):
            delete_session("a\\b", tmp_path)

    def test_load_traversal_returns_none(self, tmp_path):
        assert load_session("../evil", tmp_path) is None
