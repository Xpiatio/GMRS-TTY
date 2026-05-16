"""Verified-callsign checkmark in the chat log.

When an incoming or outgoing message names a contact whose FCC license has
been verified, the operator should see a green check next to the callsign
inline — same semantic as the verified column in Contacts, but surfaced
in the place where it actually changes how the operator interprets the
traffic (am I really hearing the licensee, or somebody using their call?).
"""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.constants import VERIFIED_COLOR, VERIFIED_GLYPH  # noqa: E402
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


def _verified_contact(callsign, name="Alice"):
    return {
        "callsign": callsign,
        "name": name,
        "location": "",
        "verified": True,
        "verified_at": "2026-01-02T03:04:05Z",
    }


def _unverified_contact(callsign, name="Bob"):
    return {
        "callsign": callsign,
        "name": name,
        "location": "",
        "verified": False,
    }


class TestVerifiedGlyph:
    def test_verified_callsign_gets_green_check(self, chat):
        chat.set_callsign_index(
            index_contacts_by_callsign([_verified_contact("WSAA111")])
        )
        chat.append_message("[RX 00:00:01]: this is WSAA111 calling")

        # The glyph is inserted directly after the callsign, separated by a
        # space, in the rendered text of the appended block.
        text = chat.toPlainText()
        assert f"WSAA111 {VERIFIED_GLYPH}" in text, text

    def test_unverified_callsign_has_no_check(self, chat):
        chat.set_callsign_index(
            index_contacts_by_callsign([_unverified_contact("WSAA222")])
        )
        chat.append_message("[RX 00:00:02]: WSAA222 here")
        assert VERIFIED_GLYPH not in chat.toPlainText()

    def test_unknown_callsign_has_no_check(self, chat):
        # Empty index means no pill and no check, even for a syntactically
        # valid GMRS callsign. The check is a property of the contact entry,
        # not the callsign itself.
        chat.set_callsign_index({})
        chat.append_message("[RX 00:00:03]: WSAA333 calling")
        assert VERIFIED_GLYPH not in chat.toPlainText()

    def test_rescan_does_not_duplicate_check(self, chat):
        """A re-scan (triggered when contacts change) must be idempotent —
        adding more contacts later mustn't pile on additional checkmarks
        after a callsign that already has one."""
        chat.set_callsign_index(
            index_contacts_by_callsign([_verified_contact("WSAA444")])
        )
        chat.append_message("[RX 00:00:04]: WSAA444 again")
        chat.rescan_all_blocks()
        chat.rescan_all_blocks()
        text = chat.toPlainText()
        assert text.count(VERIFIED_GLYPH) == 1, text

    def test_check_is_green(self, chat):
        """The check must use the verified color — same green-700 as the
        contacts dialog's verified column, so the meaning reads consistently
        across surfaces. Color is a load-bearing accessibility hint and the
        contrast value is fixed in constants.py."""
        chat.set_callsign_index(
            index_contacts_by_callsign([_verified_contact("WSAA555")])
        )
        chat.append_message("[RX 00:00:05]: WSAA555")

        text = chat.toPlainText()
        glyph_pos = text.index(VERIFIED_GLYPH)
        # Per-char format lives on the character to the left of the cursor's
        # KeepAnchor target, so we probe position glyph_pos+1.
        from PySide6.QtGui import QColor, QTextCursor
        probe = QTextCursor(chat.document())
        probe.setPosition(glyph_pos + 1)
        fmt = probe.charFormat()
        assert fmt.foreground().color() == QColor(VERIFIED_COLOR)

    def test_verified_family_member_flags_shared_callsign(self, chat):
        """Family-shared GMRS callsigns: the FCC license is held by one
        operator, so only one of the bucketed contacts will be verified.
        That single verified entry must still light up the check — the call
        as broadcast belongs to the licensed family, even if any individual
        family member spoke it."""
        index = index_contacts_by_callsign([
            _unverified_contact("WSLZ233", name="Jennifer"),
            _verified_contact("WSLZ233", name="Eliza"),
        ])
        chat.set_callsign_index(index)
        chat.append_message("[RX 00:00:06]: WSLZ233 with traffic")
        assert f"WSLZ233 {VERIFIED_GLYPH}" in chat.toPlainText()
