"""Unit tests for RXSession — no Qt required."""
import pytest

from gmrs_tty.ui.rx_session import RXSession


class _FakeChat:
    def __init__(self):
        self.messages = []   # list of (html, color)
        self.appends = []    # list of (block, text, color)
        self._next_block = 0
        self._blocks = {}    # block -> current text

    def append_message(self, html, color):
        block = self._next_block
        self._next_block += 1
        self.messages.append((html, color, block))
        self._blocks[block] = html
        return block

    def append_to_block(self, block, text, color):
        if block not in self._blocks:
            return False
        self._blocks[block] += text
        self.appends.append((block, text, color))
        return True


def _session(chat=None, completed=None):
    if chat is None:
        chat = _FakeChat()
    if completed is None:
        completed = []
    return RXSession(
        chat=chat,
        on_utterance_complete=completed.append,
        format_timestamp=lambda: "12:00:00",
    ), chat, completed


class TestSingleUtterance:
    def test_final_segment_opens_and_closes(self):
        s, chat, done = _session()
        s.receive(1, "Hello", is_final=True, color="green")
        assert len(chat.messages) == 1
        assert "Hello" in chat.messages[0][0]
        assert done == ["Hello"]

    def test_partial_then_final_grows_line(self):
        s, chat, done = _session()
        s.receive(1, "Hello", is_final=False, color="green")
        s.receive(1, "world", is_final=True, color="green")
        assert len(chat.messages) == 1
        assert len(chat.appends) == 1
        assert done == ["Hello world"]

    def test_empty_text_is_ignored(self):
        s, chat, done = _session()
        s.receive(1, "", is_final=True, color="green")
        assert chat.messages == []
        assert done == []


class TestMultipleUtterances:
    def test_new_uid_opens_new_line(self):
        s, chat, done = _session()
        s.receive(1, "First", is_final=True, color="green")
        s.receive(2, "Second", is_final=True, color="green")
        assert len(chat.messages) == 2

    def test_interrupted_utterance_flushed_on_new_uid(self):
        s, chat, done = _session()
        s.receive(1, "partial", is_final=False, color="green")
        s.receive(2, "new", is_final=True, color="green")
        # uid 1 should have been scanned when uid 2 arrived
        assert "partial" in done
        assert "new" in done


class TestChatClearedMidUtterance:
    def test_fresh_line_when_block_gone(self):
        s, chat, done = _session()
        s.receive(1, "start", is_final=False, color="green")
        # Simulate chat clear: remove the block
        chat._blocks.clear()
        # Next segment with same uid: append_to_block will return False
        s.receive(1, "more", is_final=True, color="green")
        # Should have opened a second line
        assert len(chat.messages) == 2


class TestFlush:
    def test_flush_scans_accumulated_text(self):
        s, chat, done = _session()
        s.receive(1, "partial only", is_final=False, color="green")
        s.flush()
        assert "partial only" in done

    def test_flush_empty_session_is_noop(self):
        s, chat, done = _session()
        s.flush()
        assert done == []

    def test_flush_twice_is_safe(self):
        s, chat, done = _session()
        s.receive(1, "x", is_final=False, color="green")
        s.flush()
        s.flush()
        assert done == ["x"]


class TestFilterFn:
    def test_filter_applied_before_display(self):
        chat = _FakeChat()
        done = []
        s = RXSession(
            chat=chat,
            on_utterance_complete=done.append,
            format_timestamp=lambda: "00:00:00",
            filter_fn=lambda t: t.replace("bad", "***"),
        )
        s.receive(1, "bad word", is_final=True, color="green")
        assert "***" in chat.messages[0][0]
        assert done == ["*** word"]

    def test_filter_that_empties_text_produces_no_output(self):
        chat = _FakeChat()
        s = RXSession(
            chat=chat,
            on_utterance_complete=lambda t: None,
            format_timestamp=lambda: "00:00:00",
            filter_fn=lambda _: "",
        )
        s.receive(1, "anything", is_final=True, color="green")
        assert chat.messages == []
