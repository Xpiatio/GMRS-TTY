from gmrs_tty.text.metadata import extract_name_location


class TestNameExtraction:
    def test_capitalized_word_immediately_after_callsign(self):
        # The heuristic looks for the first capitalized word right after the
        # callsign mention (after stripping punctuation).
        assert extract_name_location("WSLZ233 Bob here", "WSLZ233") == ("Bob", "")

    def test_punctuation_between_callsign_and_name_stripped(self):
        assert extract_name_location("WSLZ233, Bob, over", "WSLZ233") == ("Bob", "")

    def test_lowercase_word_after_callsign_yields_empty_name(self):
        # 'here' starts lowercase, so the [A-Z][a-z]+ regex doesn't match.
        # Location is still found independently anywhere in the text.
        assert extract_name_location("WSLZ233 here is Bob in Boston", "WSLZ233") == ("", "Boston")

    def test_callsign_not_in_text_yields_empty_name(self):
        assert extract_name_location("plain prose no callsigns", "WSLZ233") == ("", "")


class TestLocationExtraction:
    def test_in_keyword(self):
        assert extract_name_location("WSLZ233 Bob in Boston", "WSLZ233") == ("Bob", "Boston")

    def test_from_keyword(self):
        assert extract_name_location("WSLZ233 Bob from Springfield", "WSLZ233") == ("Bob", "Springfield")

    def test_near_keyword(self):
        assert extract_name_location("WSLZ233 Bob near Chicago", "WSLZ233") == ("Bob", "Chicago")

    def test_at_keyword(self):
        assert extract_name_location("WSLZ233 Bob at Denver", "WSLZ233") == ("Bob", "Denver")

    def test_multi_word_location_captured(self):
        assert extract_name_location("WSLZ233 Bob from New York", "WSLZ233") == ("Bob", "New York")

    def test_trailing_punctuation_stripped(self):
        assert extract_name_location("WSLZ233 Bob in Boston,", "WSLZ233") == ("Bob", "Boston")


class TestBothEmpty:
    def test_no_name_or_location(self):
        assert extract_name_location("WSLZ233 over and out", "WSLZ233") == ("", "")
