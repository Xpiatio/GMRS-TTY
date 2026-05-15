import datetime

import pytest

from gmrs_tty.fcc.id_rule import (
    ID_INTERVAL_SECONDS,
    format_outgoing_message,
    format_standalone_id,
)


@pytest.fixture
def now():
    return datetime.datetime(2026, 5, 15, 12, 0, 0)


@pytest.fixture
def me():
    return {"call": "WSLZ233", "name": "Bob"}


class TestUntargetedNoIdYet:
    def test_first_ever_send_appends_id(self, now, me):
        text, new_last = format_outgoing_message(
            "Hello channel",
            target_call="ALL",
            target_name="Everyone",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        assert text == "Hello channel. This is WSLZ233 Bob."
        assert new_last == now

    def test_target_empty_string_treated_as_untargeted(self, now, me):
        text, new_last = format_outgoing_message(
            "Open call",
            target_call="",
            target_name="",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        assert text == "Open call. This is WSLZ233 Bob."
        assert new_last == now


class TestUntargetedFifteenMinuteRule:
    def test_within_window_does_not_append_id(self, now, me):
        last_id = now - datetime.timedelta(minutes=10)
        text, new_last = format_outgoing_message(
            "still talking",
            target_call="ALL",
            target_name="Everyone",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=last_id,
            now=now,
        )
        assert text == "still talking"
        # Timer unchanged — we didn't ID, so the clock keeps ticking.
        assert new_last == last_id

    def test_exactly_at_threshold_does_not_append_id(self, now, me):
        # The boundary is strictly > 15 min, so exactly 15:00 should NOT trigger.
        last_id = now - datetime.timedelta(seconds=ID_INTERVAL_SECONDS)
        text, new_last = format_outgoing_message(
            "at the line",
            target_call="ALL",
            target_name="Everyone",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=last_id,
            now=now,
        )
        assert text == "at the line"
        assert new_last == last_id

    def test_just_past_threshold_appends_id_and_resets(self, now, me):
        last_id = now - datetime.timedelta(seconds=ID_INTERVAL_SECONDS + 1)
        text, new_last = format_outgoing_message(
            "checking in",
            target_call="ALL",
            target_name="Everyone",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=last_id,
            now=now,
        )
        assert text == "checking in. This is WSLZ233 Bob."
        assert new_last == now


class TestTargetedPreface:
    def test_with_target_name(self, now, me):
        text, new_last = format_outgoing_message(
            "you copy?",
            target_call="KAE1234",
            target_name="Alice",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        # Preface contains both callsigns → satisfies FCC ID on its own,
        # so the timer resets even though we didn't append a trailing ID.
        assert text == "WSLZ233 Bob calling KAE1234 Alice. you copy?"
        assert new_last == now

    def test_without_target_name(self, now, me):
        text, new_last = format_outgoing_message(
            "you copy?",
            target_call="KAE1234",
            target_name="",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        assert text == "WSLZ233 Bob calling KAE1234. you copy?"
        assert new_last == now

    def test_empty_body_text_yields_preface_only(self, now, me):
        # When you're targeting a specific station, the preface itself is the
        # call — typing no body text is valid (the operator just wants to ping).
        text, _ = format_outgoing_message(
            "",
            target_call="KAE1234",
            target_name="Alice",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        assert text == "WSLZ233 Bob calling KAE1234 Alice."

    def test_targeted_resets_timer_even_when_within_window(self, now, me):
        last_id = now - datetime.timedelta(minutes=1)
        _, new_last = format_outgoing_message(
            "ping",
            target_call="KAE1234",
            target_name="Alice",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=last_id,
            now=now,
        )
        # Preface IS a valid station ID; timer resets to `now`.
        assert new_last == now

    def test_target_call_lowercase_still_treated_as_targeted(self, now, me):
        # The dropdown might pass "ALL" or "all" interchangeably; the comparison
        # is case-insensitive.
        text, _ = format_outgoing_message(
            "msg",
            target_call="kae1234",
            target_name="alice",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        assert text == "WSLZ233 Bob calling kae1234 alice. msg"

    def test_all_lowercase_still_treated_as_untargeted(self, now, me):
        text, new_last = format_outgoing_message(
            "msg",
            target_call="all",
            target_name="Everyone",
            my_call=me["call"],
            my_name=me["name"],
            last_id_time=None,
            now=now,
        )
        # Untargeted → trailing ID appended.
        assert text == "msg. This is WSLZ233 Bob."
        assert new_last == now


class TestStandaloneId:
    def test_with_location(self, now, me):
        text, new_last = format_standalone_id(
            my_call=me["call"],
            my_name=me["name"],
            my_location="Boston",
            now=now,
        )
        assert text == "This is WSLZ233, Whiskey Sierra Lima Zulu 2 3 3. Bob from Boston."
        assert new_last == now

    def test_without_location(self, now, me):
        text, new_last = format_standalone_id(
            my_call=me["call"],
            my_name=me["name"],
            my_location="",
            now=now,
        )
        assert text == "This is WSLZ233, Whiskey Sierra Lima Zulu 2 3 3. Bob."
        assert new_last == now

    def test_whitespace_only_location_treated_as_empty(self, now, me):
        text, _ = format_standalone_id(
            my_call=me["call"],
            my_name=me["name"],
            my_location="   ",
            now=now,
        )
        assert text == "This is WSLZ233, Whiskey Sierra Lima Zulu 2 3 3. Bob."

    def test_amateur_callsign_uses_correct_nato_form(self, now):
        # K1ABC tokenized as letter-run/digit/letter-run → Kilo 1 Alpha Bravo Charlie.
        text, _ = format_standalone_id(
            my_call="K1ABC",
            my_name="Carol",
            my_location="Denver",
            now=now,
        )
        assert text == "This is K1ABC, Kilo 1 Alpha Bravo Charlie. Carol from Denver."
