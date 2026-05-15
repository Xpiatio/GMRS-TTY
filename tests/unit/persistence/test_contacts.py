from gmrs_tty.persistence.contacts import (
    format_callsign_tooltip,
    index_contacts_by_callsign,
    sort_contacts,
    sort_contacts_by_suffix,
)


class TestIndexContactsByCallsign:
    def test_indexes_by_uppercased_callsign(self):
        rows = [
            {"callsign": "wslz100", "name": "Alice"},
            {"callsign": "WSLZ100", "name": "Bob"},
            {"callsign": "KAE1234", "name": "Carol"},
        ]
        idx = index_contacts_by_callsign(rows)
        assert set(idx) == {"WSLZ100", "KAE1234"}
        assert [c["name"] for c in idx["WSLZ100"]] == ["Alice", "Bob"]

    def test_skips_all_and_empty(self):
        rows = [
            {"callsign": "ALL", "name": "Everyone"},
            {"callsign": "", "name": "Empty"},
            {"name": "Missing key"},
            {"callsign": None, "name": "None"},
            {"callsign": "WSLZ100", "name": "Real"},
        ]
        idx = index_contacts_by_callsign(rows)
        assert set(idx) == {"WSLZ100"}

    def test_empty_input(self):
        assert index_contacts_by_callsign([]) == {}
        assert index_contacts_by_callsign(None) == {}


class TestFormatCallsignTooltip:
    def test_single_entry_with_location(self):
        tip = format_callsign_tooltip(
            "WSLZ100", [{"name": "Alice", "location": "Hill Top"}]
        )
        assert tip == "WSLZ100\n  • Alice — Hill Top"

    def test_single_entry_without_location(self):
        tip = format_callsign_tooltip("WSLZ100", [{"name": "Alice"}])
        assert tip == "WSLZ100\n  • Alice"

    def test_multiple_entries_listed_in_order(self):
        tip = format_callsign_tooltip(
            "WSLZ100",
            [
                {"name": "Alice", "location": "Hill Top"},
                {"name": "Bob", "location": ""},
            ],
        )
        assert tip == "WSLZ100\n  • Alice — Hill Top\n  • Bob"

    def test_uppercases_callsign_header(self):
        tip = format_callsign_tooltip("wslz100", [{"name": "Alice"}])
        assert tip.startswith("WSLZ100\n")

    def test_missing_name_falls_back(self):
        tip = format_callsign_tooltip("WSLZ100", [{"name": "", "location": "Hill"}])
        assert "(no name)" in tip

    def test_empty_returns_empty_string(self):
        assert format_callsign_tooltip("WSLZ100", []) == ""
        assert format_callsign_tooltip("WSLZ100", None) == ""


class TestSortContacts:
    def test_all_pinned_at_index_zero(self):
        rows = [
            {"callsign": "WSLZ100", "name": "Charlie"},
            {"callsign": "All", "name": "Everyone"},
            {"callsign": "KAE9999", "name": "Bob"},
        ]
        result = sort_contacts(rows)
        assert result[0]["callsign"] == "All"

    def test_all_pinned_regardless_of_case(self):
        rows = [
            {"callsign": "WSLZ100", "name": "A"},
            {"callsign": "all", "name": "B"},
        ]
        assert sort_contacts(rows)[0]["callsign"] == "all"

    def test_alphabetical_case_insensitive(self):
        rows = [
            {"callsign": "wslz500", "name": ""},
            {"callsign": "KAE100", "name": ""},
            {"callsign": "WSLZ100", "name": ""},
        ]
        result = sort_contacts(rows)
        # K, W, w — alphabetical, case-insensitive
        assert [r["callsign"] for r in result] == ["KAE100", "WSLZ100", "wslz500"]

    def test_tiebreak_by_name(self):
        rows = [
            {"callsign": "WSLZ100", "name": "Zoe"},
            {"callsign": "WSLZ100", "name": "Alice"},
        ]
        result = sort_contacts(rows)
        assert [r["name"] for r in result] == ["Alice", "Zoe"]

    def test_missing_fields_handled(self):
        # The helper coerces missing/None fields to empty strings.
        rows = [{"callsign": None}, {"name": "noname"}]
        result = sort_contacts(rows)
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        assert sort_contacts([]) == []


class TestSortContactsBySuffix:
    def test_all_pinned_at_index_zero(self):
        rows = [
            {"callsign": "WSLZ100", "name": ""},
            {"callsign": "ALL", "name": ""},
            {"callsign": "WSLZ050", "name": ""},
        ]
        result = sort_contacts_by_suffix(rows)
        assert result[0]["callsign"] == "ALL"

    def test_sorted_by_last_three_digits(self):
        rows = [
            {"callsign": "WSLZ500", "name": ""},
            {"callsign": "KAE100", "name": ""},
            {"callsign": "WSLZ300", "name": ""},
        ]
        result = sort_contacts_by_suffix(rows)
        assert [r["callsign"] for r in result] == ["KAE100", "WSLZ300", "WSLZ500"]

    def test_legacy_four_digit_uses_last_three(self):
        # KAE1234 → '234'; WSLZ100 → '100'. 100 < 234, so WSLZ100 first.
        rows = [
            {"callsign": "KAE1234", "name": ""},
            {"callsign": "WSLZ100", "name": ""},
        ]
        result = sort_contacts_by_suffix(rows)
        assert [r["callsign"] for r in result] == ["WSLZ100", "KAE1234"]

    def test_no_trailing_digits_sorts_to_end(self):
        rows = [
            {"callsign": "WSLZ100", "name": ""},
            {"callsign": "ALPHA", "name": ""},
        ]
        result = sort_contacts_by_suffix(rows)
        # WSLZ100 has digits → bucket 1; ALPHA → bucket 2 (end).
        assert [r["callsign"] for r in result] == ["WSLZ100", "ALPHA"]
