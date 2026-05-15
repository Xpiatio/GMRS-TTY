import pytest

from gmrs_tty.text.callsigns import (
    callsign_to_nato,
    detect_callsigns,
    spell_digits_in_callsigns,
)


class TestDetectCallsignsEmptyInputs:
    def test_none_returns_empty(self):
        assert detect_callsigns(None) == []

    def test_empty_string_returns_empty(self):
        assert detect_callsigns("") == []

    def test_no_callsign_returns_empty(self):
        assert detect_callsigns("just text, nothing radio-shaped here") == []


class TestDetectCallsignsCompactForms:
    def test_gmrs_modern(self):
        assert detect_callsigns("WSLZ233 here") == ["WSLZ233"]

    def test_gmrs_legacy_three_digit(self):
        assert detect_callsigns("KAE123 calling") == ["KAE123"]

    def test_gmrs_legacy_four_digit(self):
        assert detect_callsigns("KAE1234 calling") == ["KAE1234"]

    def test_us_amateur_one_by_three(self):
        assert detect_callsigns("K1ABC here") == ["K1ABC"]

    def test_us_amateur_two_by_three(self):
        assert detect_callsigns("KD9XYZ here") == ["KD9XYZ"]

    def test_us_amateur_one_by_two(self):
        assert detect_callsigns("W1AW broadcasting") == ["W1AW"]

    def test_lowercase_input_is_normalized_to_upper(self):
        assert detect_callsigns("wslz233 over") == ["WSLZ233"]

    def test_multiple_distinct_callsigns_sorted(self):
        # Output is sorted alphabetically (set internally, sorted on return).
        assert detect_callsigns("WSLZ233 and KAE1234") == ["KAE1234", "WSLZ233"]


class TestDetectCallsignsSpacedAndSeparated:
    def test_space_separated_chars(self):
        assert detect_callsigns("W S L Z 2 3 3") == ["WSLZ233"]

    def test_dot_separated_chars(self):
        assert detect_callsigns("W.S.L.Z.2.3.3") == ["WSLZ233"]

    def test_comma_separated_chars(self):
        assert detect_callsigns("W, S, L, Z, 2, 3, 3") == ["WSLZ233"]

    def test_letter_block_dash_digits(self):
        assert detect_callsigns("WSLZ-233") == ["WSLZ233"]

    def test_letter_block_dot_digits(self):
        assert detect_callsigns("WSLZ.233") == ["WSLZ233"]

    def test_letter_block_comma_digits(self):
        assert detect_callsigns("WSLZ, 233") == ["WSLZ233"]

    def test_letter_block_space_digits(self):
        assert detect_callsigns("WSLZ 233") == ["WSLZ233"]


class TestDetectCallsignsPhonetic:
    def test_nato_phonetic_titlecase(self):
        assert detect_callsigns("Whiskey Sierra Lima Zulu Two Three Three") == ["WSLZ233"]

    def test_nato_phonetic_lowercase(self):
        assert detect_callsigns("whiskey sierra lima zulu two three three") == ["WSLZ233"]

    def test_nato_phonetic_with_xray_hyphen(self):
        # 'X-ray' is normalized to 'Xray' so it becomes a single 'X' letter.
        # Whiskey X-ray Sierra Zulu = WXSZ, which fits W[A-Z]{3}\d{3}.
        assert detect_callsigns("Whiskey X-ray Sierra Zulu Two Three Three") == ["WXSZ233"]

    def test_nato_phonetic_with_xray_space(self):
        assert detect_callsigns("Whiskey X ray Sierra Zulu Two Three Three") == ["WXSZ233"]

    def test_juliet_variant_juliett(self):
        # The phonetic alphabet table accepts both 'Juliet' and 'Juliett'.
        assert detect_callsigns("Whiskey Juliett Lima Zulu Two Three Three") == ["WJLZ233"]


class TestCallsignToNato:
    def test_modern_gmrs(self):
        assert callsign_to_nato("WSLZ233") == "Whiskey Sierra Lima Zulu 2 3 3"

    def test_amateur_with_interior_digit(self):
        assert callsign_to_nato("K1ABC") == "Kilo 1 Alpha Bravo Charlie"

    def test_lowercase_input_is_upper_cased(self):
        assert callsign_to_nato("wslz233") == "Whiskey Sierra Lima Zulu 2 3 3"

    def test_empty(self):
        assert callsign_to_nato("") == ""

    def test_x_uses_x_ray_token(self):
        # X is the only letter whose NATO form contains a hyphen — preserve it.
        assert callsign_to_nato("WXSZ233") == "Whiskey X-ray Sierra Zulu 2 3 3"


class TestSpellDigitsInCallsigns:
    def test_gmrs_modern(self):
        assert spell_digits_in_callsigns("Hello WSLZ233") == "Hello WSLZ 2 3 3"

    def test_amateur_with_interior_digit(self):
        assert spell_digits_in_callsigns("K1ABC says hi") == "K 1 ABC says hi"

    def test_legacy_four_digit(self):
        assert spell_digits_in_callsigns("KAE1234 calling") == "KAE 1 2 3 4 calling"

    def test_multiple_callsigns_spelled_independently(self):
        assert (
            spell_digits_in_callsigns("two WSLZ233 in row KAE1234")
            == "two WSLZ 2 3 3 in row KAE 1 2 3 4"
        )

    def test_non_callsign_text_left_alone(self):
        assert spell_digits_in_callsigns("just plain text 100") == "just plain text 100"
