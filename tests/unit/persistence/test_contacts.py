from gmrs_tty.persistence.contacts import (
    format_callsign_tooltip,
    index_contacts_by_callsign,
    known_callsigns,
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

    def test_indexes_under_gmrs_and_ham_fields(self):
        """A verified contact carries its full FCC cross-reference (primary
        callsign + gmrs_callsign + ham_callsign), and the chat highlighter
        needs to find the contact whichever form a remote operator speaks."""
        rows = [
            {"callsign": "KE8RXN", "name": "Collin",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ]
        idx = index_contacts_by_callsign(rows)
        assert set(idx) == {"KE8RXN", "WRPN553"}
        # Same contact reachable from either key.
        assert idx["KE8RXN"][0]["name"] == "Collin"
        assert idx["WRPN553"][0]["name"] == "Collin"

    def test_does_not_duplicate_when_primary_equals_cross_reference(self):
        """Common case: primary callsign === one of the cross-reference fields
        (e.g. primary 'KE8RXN', ham_callsign 'KE8RXN'). The contact must
        appear exactly once under that key, not twice."""
        rows = [
            {"callsign": "KE8RXN", "name": "Collin",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ]
        idx = index_contacts_by_callsign(rows)
        assert len(idx["KE8RXN"]) == 1

    def test_family_members_share_indices_across_callsign_forms(self):
        rows = [
            {"callsign": "WSLZ233", "name": "Benjamin",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8ZZZ"},
            {"callsign": "WSLZ233", "name": "Eliza",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8ZZZ"},
        ]
        idx = index_contacts_by_callsign(rows)
        # Both family rows reachable under either callsign form.
        assert [c["name"] for c in idx["WSLZ233"]] == ["Benjamin", "Eliza"]
        assert [c["name"] for c in idx["KD8ZZZ"]] == ["Benjamin", "Eliza"]

    def test_skips_empty_cross_reference_fields(self):
        rows = [
            {"callsign": "WSAC909", "name": "Tim",
             "gmrs_callsign": "WSAC909", "ham_callsign": ""},
        ]
        idx = index_contacts_by_callsign(rows)
        assert set(idx) == {"WSAC909"}


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

    def test_includes_gmrs_and_ham_lines_when_present(self):
        tip = format_callsign_tooltip("KE8RXN", [
            {"name": "Collin", "location": "Grand Rapids",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ])
        # Each entry's block is: name — location, then GMRS / HAM detail lines.
        assert "Collin" in tip
        assert "Grand Rapids" in tip
        assert "GMRS: WRPN553" in tip
        assert "HAM: KE8RXN" in tip

    def test_omits_cross_reference_lines_when_missing(self):
        # Unverified contact without cross-references: don't fabricate empty
        # 'GMRS:' / 'HAM:' lines.
        tip = format_callsign_tooltip("WSAC909", [
            {"name": "Tim", "location": "Zeeland"}
        ])
        assert "GMRS:" not in tip
        assert "HAM:" not in tip

    def test_lists_all_entries_with_full_per_entry_info(self):
        """Family members on a shared callsign each get their own block with
        name + location + (when present) GMRS / HAM cross-references."""
        tip = format_callsign_tooltip("WSLZ233", [
            {"name": "Benjamin", "location": "Jenison",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8AAA"},
            {"name": "Eliza", "location": "Jenison",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8BBB"},
        ])
        assert "Benjamin" in tip and "Eliza" in tip
        assert "KD8AAA" in tip and "KD8BBB" in tip


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


class TestKnownCallsigns:
    """known_callsigns powers the 'is this station already a contact?' check
    that suppresses the '+ Add' pill for stations detected in RX. It must
    consider every callsign field on every contact so a HAM call detected
    over the air doesn't show a redundant Add pill when that operator's
    GMRS call is already saved (and vice versa)."""

    def test_empty_inputs(self):
        assert known_callsigns([]) == set()
        assert known_callsigns(None) == set()

    def test_collects_primary_field(self):
        rows = [{"callsign": "WSLZ233", "name": "Benjamin"}]
        assert known_callsigns(rows) == {"WSLZ233"}

    def test_collects_gmrs_and_ham_fields(self):
        rows = [
            {"callsign": "KE8RXN", "name": "Collin",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ]
        assert known_callsigns(rows) == {"KE8RXN", "WRPN553"}

    def test_uppercases_and_dedupes(self):
        rows = [
            {"callsign": "ke8rxn", "name": "Collin",
             "gmrs_callsign": "wrpn553", "ham_callsign": "KE8RXN"},
        ]
        assert known_callsigns(rows) == {"KE8RXN", "WRPN553"}

    def test_skips_all_and_empty(self):
        rows = [
            {"callsign": "ALL", "name": "Everyone"},
            {"callsign": "", "name": "blank"},
            {"callsign": "WSLZ233", "name": "Benjamin",
             "gmrs_callsign": "", "ham_callsign": None},
        ]
        assert known_callsigns(rows) == {"WSLZ233"}

    def test_family_rows_contribute_each_distinct_callsign(self):
        # Family on a shared GMRS call, each with their own HAM call. All
        # five callsigns (one shared GMRS + three HAMs + the primaries that
        # happen to equal the GMRS) collapse to the right unique set.
        rows = [
            {"callsign": "WSLZ233", "name": "Benjamin",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8AAA"},
            {"callsign": "WSLZ233", "name": "Eliza",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8BBB"},
            {"callsign": "WSLZ233", "name": "Jennifer",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8CCC"},
        ]
        assert known_callsigns(rows) == {"WSLZ233", "KD8AAA", "KD8BBB", "KD8CCC"}


class TestVerificationFieldsRoundTrip:
    """Pin that the verification metadata (verified / verified_at / license_name)
    survives the sort + index helpers. They operate on dicts, so this is just a
    regression guard against someone narrowing the helpers to a fixed schema."""

    def test_sort_preserves_verified_flag(self):
        rows = [
            {"callsign": "WSLZ100", "name": "Alice",
             "verified": True, "verified_at": "2026-05-16T20:00:00Z"},
            {"callsign": "KAE100", "name": "Bob"},
        ]
        result = sort_contacts(rows)
        wslz = next(r for r in result if r["callsign"] == "WSLZ100")
        assert wslz["verified"] is True
        assert wslz["verified_at"] == "2026-05-16T20:00:00Z"

    def test_index_preserves_verified_flag(self):
        rows = [{"callsign": "WSLZ100", "name": "Alice", "verified": True}]
        idx = index_contacts_by_callsign(rows)
        assert idx["WSLZ100"][0]["verified"] is True
