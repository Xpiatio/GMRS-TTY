from gmrs_tty.text.shorthand import expand_tty_abbreviations


class TestUniversalTerms:
    def test_ga(self):
        assert expand_tty_abbreviations("GA Bob") == "Go ahead Bob"

    def test_sk(self):
        assert expand_tty_abbreviations("SK now") == "Stop keying now"

    def test_sksk_takes_precedence_over_sk(self):
        # Longest-key-first ordering: SKSK must match before SK.
        assert expand_tty_abbreviations("SKSK") == "Hanging up"

    def test_ga_to_sk_takes_precedence_over_ga_and_sk(self):
        assert (
            expand_tty_abbreviations("GA TO SK")
            == "Completing messages and getting ready to hang up"
        )

    def test_q_question_mark(self):
        assert expand_tty_abbreviations("Bob Q") == "Bob Question mark"

    def test_xxxx_erasing_error(self):
        assert expand_tty_abbreviations("oops XXXX done") == "oops Erasing the error done"


class TestCommonTerms:
    def test_asap(self):
        assert expand_tty_abbreviations("Call ASAP") == "Call As soon as possible"

    def test_ily(self):
        assert expand_tty_abbreviations("ILY mom") == "I love you mom"

    def test_cul(self):
        assert expand_tty_abbreviations("CUL friend") == "See you later friend"

    def test_msg(self):
        assert expand_tty_abbreviations("got your MSG") == "got your Message"


class TestCaseInsensitivity:
    def test_lowercase_matches(self):
        assert expand_tty_abbreviations("ga lowercase") == "Go ahead lowercase"

    def test_mixed_case_matches(self):
        assert expand_tty_abbreviations("Asap") == "As soon as possible"


class TestWordBoundaries:
    def test_q_inside_qso_not_expanded(self):
        # 'QSO' is amateur radio shorthand we leave alone — only standalone Q expands.
        assert expand_tty_abbreviations("QSO traffic") == "QSO traffic"

    def test_dr_inside_doctor_not_expanded(self):
        # 'Doctor' must survive unchanged even though 'DR' is in the table.
        assert expand_tty_abbreviations("Doctor uses DR shorthand") == "Doctor uses Doctor shorthand"

    def test_msg_inside_messaging_not_expanded(self):
        assert expand_tty_abbreviations("messaging system") == "messaging system"

    def test_no_match_unchanged(self):
        assert expand_tty_abbreviations("plain prose with no shorthand") == (
            "plain prose with no shorthand"
        )

    def test_empty_string(self):
        assert expand_tty_abbreviations("") == ""
