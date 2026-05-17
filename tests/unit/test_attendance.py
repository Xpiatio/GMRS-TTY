from gmrs_tty.persistence.attendance import (
    AttendanceTracker,
    build_attendance_rows,
)


class TestAttendanceTracker:
    def test_record_returns_true_only_on_first_sighting(self):
        t = AttendanceTracker()
        assert t.record("WSLZ100") is True
        assert t.record("WSLZ100") is False
        assert t.record("wslz100") is False  # case-insensitive dedup

    def test_record_normalizes_to_upper(self):
        t = AttendanceTracker()
        t.record("wslz100")
        assert t.callsigns() == ["WSLZ100"]
        assert "WSLZ100" in t
        assert "wslz100" in t

    def test_blank_callsigns_are_ignored(self):
        t = AttendanceTracker()
        assert t.record("") is False
        assert t.record(None) is False
        assert t.record("   ") is False
        assert len(t) == 0

    def test_callsigns_returned_in_insertion_order(self):
        t = AttendanceTracker()
        for cs in ("WSLZ100", "KAE1234", "K1ABC"):
            t.record(cs)
        assert t.callsigns() == ["WSLZ100", "KAE1234", "K1ABC"]

    def test_clear_empties_state(self):
        t = AttendanceTracker()
        t.record("WSLZ100")
        t.clear()
        assert t.callsigns() == []
        assert "WSLZ100" not in t
        assert len(t) == 0
        # Cleared tracker re-records the same callsign as new.
        assert t.record("WSLZ100") is True


class TestBuildAttendanceRows:
    def test_unknown_callsign_returns_blank_columns(self):
        rows = build_attendance_rows(["WSLZ100"], contacts=[])
        assert rows == [{
            "callsign": "WSLZ100",
            "name": "",
            "location": "",
            "gmrs": "",
            "ham": "",
        }]

    def test_contact_match_populates_name_location_gmrs_ham(self):
        contacts = [{
            "callsign": "WSLZ100",
            "name": "Alice",
            "location": "Lansing",
            "gmrs_callsign": "WSLZ100",
            "ham_callsign": "K1ABC",
        }]
        rows = build_attendance_rows(["WSLZ100"], contacts)
        assert rows[0]["name"] == "Alice"
        assert rows[0]["location"] == "Lansing"
        assert rows[0]["gmrs"] == "WSLZ100"
        assert rows[0]["ham"] == "K1ABC"

    def test_match_via_ham_field(self):
        # Contact's primary is GMRS but their HAM cross-reference matches.
        contacts = [{
            "callsign": "WSLZ100",
            "name": "Alice",
            "location": "Lansing",
            "ham_callsign": "K1ABC",
        }]
        rows = build_attendance_rows(["K1ABC"], contacts)
        assert rows[0]["callsign"] == "K1ABC"
        assert rows[0]["name"] == "Alice"

    def test_preserves_callsign_order(self):
        contacts = [{"callsign": "WSLZ100", "name": "Alice"}]
        rows = build_attendance_rows(["KAE1234", "WSLZ100", "K1ABC"], contacts)
        assert [r["callsign"] for r in rows] == ["KAE1234", "WSLZ100", "K1ABC"]

    def test_family_shared_callsign_picks_first_entry(self):
        contacts = [
            {"callsign": "WSLZ100", "name": "Alice", "location": "Lansing"},
            {"callsign": "WSLZ100", "name": "Bob", "location": "Lansing"},
        ]
        rows = build_attendance_rows(["WSLZ100"], contacts)
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"

    def test_blank_or_missing_fields_become_empty_strings(self):
        contacts = [{"callsign": "WSLZ100"}]
        rows = build_attendance_rows(["WSLZ100"], contacts)
        assert rows[0]["name"] == ""
        assert rows[0]["location"] == ""
        assert rows[0]["gmrs"] == ""
        assert rows[0]["ham"] == ""

    def test_case_insensitive_lookup(self):
        contacts = [{"callsign": "wslz100", "name": "Alice"}]
        rows = build_attendance_rows(["WSLZ100"], contacts)
        assert rows[0]["name"] == "Alice"

    def test_empty_callsigns_skipped(self):
        rows = build_attendance_rows(["", None, "WSLZ100"], contacts=[])
        assert [r["callsign"] for r in rows] == ["WSLZ100"]
