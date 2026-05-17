"""Nickname → canonical-name expansion.

Tested independently from the FCC verification path so the table and
``canonical_forms`` contract can evolve without churning the higher-level
crossref tests. The integration with name_matches lives in
``tests/unit/fcc/test_crossref.py::TestNameMatchNicknames``.
"""

from gmrs_tty.text.nicknames import canonical_forms, NICKNAMES


class TestCanonicalForms:
    def test_known_nickname_includes_canonical(self):
        # 'Dick' expanding to {'dick', 'richard'} is the load-bearing
        # property — it's what lets a contact entered as 'Dick' verify
        # against an FCC license held under 'Richard'.
        forms = canonical_forms("Dick")
        assert "dick" in forms
        assert "richard" in forms

    def test_unknown_token_returns_self_only(self):
        # A canonical first name or a last name has no mapping; falling
        # through to {self} lets the matcher use the same set-intersection
        # logic for every token without special-casing.
        assert canonical_forms("Smith") == frozenset({"smith"})

    def test_empty_input_returns_empty(self):
        assert canonical_forms("") == frozenset()
        assert canonical_forms(None) == frozenset()

    def test_lowercasing_is_applied(self):
        # The table is keyed on lowercase to keep a single canonical
        # representation; callers shouldn't have to lowercase first.
        assert canonical_forms("BOB") == canonical_forms("bob")
        assert "robert" in canonical_forms("BOB")

    def test_multi_canonical_nickname(self):
        # 'Sandy' → {Alexander, Sandra}. Both canonicals must appear so the
        # matcher can pick whichever side the FCC record uses.
        forms = canonical_forms("sandy")
        assert "alexander" in forms
        assert "sandra" in forms
        assert "sandy" in forms

    def test_returned_set_is_immutable_view(self):
        # canonical_forms must not hand back a reference the caller can
        # mutate into the shared table.
        forms = canonical_forms("bob")
        assert isinstance(forms, frozenset)


class TestNicknamesTable:
    def test_all_keys_lowercase(self):
        # Keys are normalized on insertion; a stray capital letter would
        # silently fail lookups since canonical_forms lowercases input.
        for key in NICKNAMES:
            assert key == key.lower(), key

    def test_all_canonicals_lowercase(self):
        for key, canonicals in NICKNAMES.items():
            for c in canonicals:
                assert c == c.lower(), (key, c)

    def test_includes_user_requested_examples(self):
        # User specifically called out Dick→Richard and Tom→Thomas in the
        # ask. Tom is a prefix match (handled by name_matches without the
        # table) so it doesn't need a row, but Dick is the load-bearing
        # case — the suite should fail loudly if it goes missing.
        assert "richard" in NICKNAMES["dick"]
