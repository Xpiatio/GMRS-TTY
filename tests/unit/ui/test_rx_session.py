"""Unit tests for RXSession — no Qt required."""
from gmrs_tty.ui.rx_session import RXSession


class _FakeChat:
    def __init__(self):
        self.messages = []      # list of (html, color)
        self.appends = []       # list of (block, text, color)
        self.replacements = []  # list of (block, html, color)
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

    def replace_block(self, block, html, color):
        if block not in self._blocks:
            return False
        self._blocks[block] = html
        self.replacements.append((block, html, color))
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


class TestReplaceSemantics:
    def test_replace_rewrites_open_line_and_closes(self):
        session, chat, completed = _session()
        session.receive(1, "hello bob", False, "green")
        session.receive(1, "hello bob", False, "green")  # demoted fast tail
        session.receive(1, "hello bob how are you", True, "green", replace=True)
        assert len(chat.replacements) == 1
        block, html, _color = chat.replacements[0]
        assert html == "<b>[RX 12:00:00]:</b> hello bob how are you"
        assert completed == ["hello bob how are you"]
        # Utterance closed: the next partial opens a fresh line.
        session.receive(2, "next", False, "green")
        assert len(chat.messages) == 2

    def test_replace_after_chat_cleared_opens_fresh_line(self):
        session, chat, completed = _session()
        session.receive(1, "partial", False, "green")
        chat._blocks.clear()  # simulate Clear chat
        session.receive(1, "full text", True, "green", replace=True)
        assert chat.replacements == []
        assert len(chat.messages) == 2  # original + reopened line
        assert completed == ["full text"]

    def test_late_replace_does_not_disturb_newer_utterance(self):
        session, chat, completed = _session()
        session.receive(1, "old partial", False, "green")
        session.receive(2, "new partial", False, "green")  # flushes uid 1
        session.receive(1, "old full text", True, "green", replace=True)
        # Replacement landed as its own line; uid 2 still open and growable.
        assert completed == ["old partial", "old full text"]
        session.receive(2, "more", True, "green")
        assert completed[-1] == "new partial more"

    def test_empty_final_closes_line_without_output(self):
        session, chat, completed = _session()
        session.receive(1, "partial text", False, "green")
        session.receive(1, "", True, "green")  # abandoned final pass
        assert completed == ["partial text"]
        session.receive(2, "next", False, "green")
        assert len(chat.messages) == 2

    def test_empty_final_for_unknown_uid_is_noop(self):
        session, chat, completed = _session()
        session.receive(7, "", True, "green")
        assert chat.messages == []
        assert completed == []
