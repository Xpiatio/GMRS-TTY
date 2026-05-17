"""Fuzzy callsign logic in the chat log.

When the operator opts in via the `fuzzy_callsign` config flag, an incoming
callsign that differs from a known contact by exactly one character should
be rewritten in the chat to the known canonical form and pill-highlighted.
The toggle is off by default — silent edits to RX traffic shouldn't happen
without an explicit opt-in.
"""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.persistence.contacts import index_contacts_by_callsign  # noqa: E402
from gmrs_tty.ui.chat_display import ChatDisplay  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def chat(qapp):
    widget = ChatDisplay()
    yield widget
    widget.close()


def _contact(callsign, name="Operator"):
    return {"callsign": callsign, "name": name, "location": "", "verified": False}


class TestFuzzyCallsignReplacement:
    def test_off_by_one_digit_is_rewritten_when_enabled(self, chat):
        chat.set_callsign_index(
            index_contacts_by_callsign([_contact("WSLZ233", name="Ben")])
        )
        chat.set_fuzzy_enabled(True)
        chat.append_message("[RX 00:00:01]: this is WSLZ234 calling")

        text = chat.toPlainText()
        assert "WSLZ234" not in text
        assert "WSLZ233" in text

    def test_off_by_one_letter_is_rewritten_when_enabled(self, chat):
        # Whisper commonly hears 'L' as 'I' — STT-style miss the toggle
        # exists to forgive.
        chat.set_callsign_index(
            index_contacts_by_callsign([_contact("WSLZ233")])
        )
        chat.set_fuzzy_enabled(True)
        chat.append_message("[RX 00:00:02]: WSIZ233 with traffic")

        text = chat.toPlainText()
        assert "WSIZ233" not in text
        assert "WSLZ233" in text

    def test_off_by_one_not_rewritten_when_disabled(self, chat):
        # Default-off: the operator must opt in before we edit their traffic
        # log. Without the toggle, the chat shows what STT produced.
        chat.set_callsign_index(
            index_contacts_by_callsign([_contact("WSLZ233")])
        )
        chat.set_fuzzy_enabled(False)
        chat.append_message("[RX 00:00:03]: WSLZ234 here")

        text = chat.toPlainText()
        assert "WSLZ234" in text
        assert "WSLZ233" not in text

    def test_two_off_is_left_alone(self, chat):
        # Two characters off is a different callsign, not a typo.
        chat.set_callsign_index(
            index_contacts_by_callsign([_contact("WSLZ233")])
        )
        chat.set_fuzzy_enabled(True)
        chat.append_message("[RX 00:00:04]: WSLZ244 here")

        text = chat.toPlainText()
        assert "WSLZ244" in text
        assert "WSLZ233" not in text

    def test_ambiguous_match_is_left_alone(self, chat):
        # Two contacts equidistant from the detected call — picking either
        # silently would be wrong as often as it is right.
        chat.set_callsign_index(
            index_contacts_by_callsign([
                _contact("WSLZ233", name="Alice"),
                _contact("WSLZ235", name="Bob"),
            ])
        )
        chat.set_fuzzy_enabled(True)
        chat.append_message("[RX 00:00:05]: WSLZ234 calling")

        text = chat.toPlainText()
        assert "WSLZ234" in text

    def test_exact_match_unaffected(self, chat):
        # Regression guard: enabling fuzzy must not mangle exact hits.
        chat.set_callsign_index(
            index_contacts_by_callsign([_contact("WSLZ233")])
        )
        chat.set_fuzzy_enabled(True)
        chat.append_message("[RX 00:00:06]: WSLZ233 over")

        assert chat.toPlainText().count("WSLZ233") == 1

    def test_rewrite_pills_the_replacement(self, chat):
        """The rewritten token must carry the pill format — that's the whole
        point of the toggle: a contact's call shows up as a contact pill
        even when STT misheard a single character."""
        from PySide6.QtGui import QFont, QTextCursor
        chat.set_callsign_index(
            index_contacts_by_callsign([_contact("WSLZ233")])
        )
        chat.set_fuzzy_enabled(True)
        chat.append_message("[RX 00:00:07]: WSLZ234 here")

        text = chat.toPlainText()
        idx = text.index("WSLZ233")
        probe = QTextCursor(chat.document())
        probe.setPosition(idx + 1)
        fmt = probe.charFormat()
        assert fmt.fontWeight() == QFont.Weight.Bold
        assert fmt.background().style() != 0  # NoBrush = 0; pill sets a real brush
