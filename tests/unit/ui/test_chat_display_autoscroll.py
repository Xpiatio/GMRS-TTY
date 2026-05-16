"""ChatDisplay must tail new messages while preserving scroll-up history reads.

The operator relies on the chat log as a live transcript of radio traffic,
so a message arriving while they're already at the bottom needs to remain
in view. But if they've scrolled up to re-read earlier context, an incoming
transmission must not yank them away from what they're reading."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.ui.chat_display import ChatDisplay  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def chat(qapp):
    widget = ChatDisplay()
    # A small fixed viewport forces the scrollbar to engage once a handful
    # of messages have been appended, which is what makes the
    # at-bottom-vs-scrolled-up branches observable.
    widget.resize(200, 60)
    widget.show()
    yield widget
    widget.close()


def _fill_until_scrollable(widget, min_range=20, max_lines=400):
    """Append messages until the scrollbar has a comfortable scroll range.

    We need more than a 1-pixel range so the "scrolled up" branch can park
    the viewport well outside the at-bottom tolerance (2 px) — otherwise
    both branches collapse together and the test stops proving anything."""
    for i in range(max_lines):
        widget.append_message(f"line {i}")
        if widget.verticalScrollBar().maximum() >= min_range:
            return
    raise AssertionError(
        f"scrollbar range never reached {min_range} px in test viewport"
    )


class TestAutoScroll:
    def test_sticks_to_bottom_when_at_bottom(self, chat):
        _fill_until_scrollable(chat)
        sb = chat.verticalScrollBar()
        sb.setValue(sb.maximum())
        assert sb.value() == sb.maximum()

        chat.append_message("incoming after caught up")

        sb = chat.verticalScrollBar()
        assert sb.value() == sb.maximum(), (
            "new message should have scrolled the view to the new bottom"
        )

    def test_preserves_position_when_scrolled_up(self, chat):
        _fill_until_scrollable(chat)
        sb = chat.verticalScrollBar()
        # Park the viewport well above the bottom so the at-bottom tolerance
        # (2 px) cannot accidentally count this as "still tailing".
        parked = max(0, sb.maximum() // 2)
        sb.setValue(parked)
        assert sb.value() < sb.maximum() - 2

        chat.append_message("incoming while reading history")

        sb = chat.verticalScrollBar()
        assert sb.value() == parked, (
            "scroll position must not jump when operator is reading older lines"
        )
