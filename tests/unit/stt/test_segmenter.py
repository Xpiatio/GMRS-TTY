"""Unit tests for SpeechSegmenter.

These tests avoid loading any ML model by injecting stub VAD iterators and
SquelchDetector instances, exercising only the state machine logic.
"""
import numpy as np
import pytest

from gmrs_tty.audio.squelch import SquelchDetector
from gmrs_tty.stt.segmenter import SpeechSegmenter


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _NeverFiringVad:
    """VAD that never detects speech — simulates silence."""
    def __call__(self, chunk, return_seconds=False):
        return {}

    def reset(self):
        pass


class _ScriptedVad:
    """VAD whose response is driven by a list of (start|end|None) strings."""
    def __init__(self, script):
        self._script = iter(script)

    def __call__(self, chunk, return_seconds=False):
        try:
            action = next(self._script)
        except StopIteration:
            return {}
        if action == "start":
            return {"start": 0}
        if action == "end":
            return {"end": 0}
        return {}

    def reset(self):
        pass


def _make_squelch_always_open():
    sq = SquelchDetector(open_threshold=0.0, open_hold_chunks=0, close_hold_chunks=9999)
    # Force open state by feeding a non-zero peak.
    sq.update(1.0)
    return sq


def _segmenter(vad_iter, squelch=None, **kwargs):
    if squelch is None:
        squelch = SquelchDetector(open_threshold=0.0, open_hold_chunks=0, close_hold_chunks=9999)
    defaults = dict(
        sample_rate=16000,
        rolling_target_chunks=4,
        cut_window_chunks=2,
        pre_buffer_chunks=2,
        squelch_buffer_max_chunks=4,
        min_speech_duration_s=0.0,
        silence_reset_chunks=100,
    )
    defaults.update(kwargs)
    return SpeechSegmenter(vad_iter, squelch, **defaults)


_CHUNK = np.zeros(512, dtype=np.float32)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSilenceProducesNoSegments:
    def test_no_output_during_silence(self):
        seg = _segmenter(_NeverFiringVad())
        for _ in range(10):
            segments, events = seg.feed(_CHUNK, 0.0)
        assert segments == []
        assert events == []


class TestVadStartEnd:
    def test_short_utterance_emits_final_segment(self):
        # script: start, in-speech, end
        vad = _ScriptedVad(["start", None, "end"])
        seg = _segmenter(vad)
        all_segments = []
        for _ in range(3):
            s, _ = seg.feed(_CHUNK, 0.0)
            all_segments.extend(s)
        assert len(all_segments) == 1
        uid, audio, is_final = all_segments[0]
        assert is_final is True
        assert isinstance(audio, np.ndarray)

    def test_short_utterance_uid_increments(self):
        vad = _ScriptedVad(["start", "end", None, "start", "end"])
        seg = _segmenter(vad)
        all_segs = []
        for _ in range(5):
            s, _ = seg.feed(_CHUNK, 0.0)
            all_segs.extend(s)
        assert len(all_segs) == 2
        assert all_segs[1][0] == all_segs[0][0] + 1  # uid increments

    def test_vad_events_emitted(self):
        vad = _ScriptedVad(["start", "end"])
        seg = _segmenter(vad)
        all_events = []
        for _ in range(2):
            _, events = seg.feed(_CHUNK, 0.0)
            all_events.extend(events)
        assert "vad_start" in all_events
        assert "vad_end" in all_events


class TestRollingSegmentSlice:
    def test_long_utterance_emits_partial_then_final(self):
        # rolling_target=2, cut_window=1, slice_trigger=3
        # script: start, then 4 in-speech chunks (triggers slice at 3), then end
        vad = _ScriptedVad(["start"] + [None] * 4 + ["end"])
        seg = _segmenter(vad, rolling_target_chunks=2, cut_window_chunks=1)
        all_segs = []
        for _ in range(6):
            s, _ = seg.feed(_CHUNK, 0.0)
            all_segs.extend(s)
        partials = [s for s in all_segs if not s[2]]
        finals = [s for s in all_segs if s[2]]
        assert len(partials) >= 1
        assert len(finals) == 1
        assert partials[0][0] == finals[0][0]  # same uid


class TestMinSpeechDuration:
    def test_too_short_utterance_dropped_when_no_partials(self):
        # With min_speech_duration_s=0.1 and SAMPLE_RATE=16000, need >=1600 samples.
        # Each _CHUNK is 512 samples, so one chunk = 32ms < 100ms — should be dropped.
        vad = _ScriptedVad(["start", "end"])
        seg = _segmenter(vad, sample_rate=16000, min_speech_duration_s=0.1)
        all_segs = []
        for _ in range(2):
            s, _ = seg.feed(_CHUNK, 0.0)
            all_segs.extend(s)
        assert all_segs == []

    def test_utterance_not_dropped_when_partials_emitted(self):
        # rolling_target=2, cut_window=1 → slice after 3 chunks; then end
        vad = _ScriptedVad(["start"] + [None] * 3 + ["end"])
        seg = _segmenter(
            vad,
            sample_rate=16000,
            min_speech_duration_s=999.0,  # impossibly long — but partial forces keep
            rolling_target_chunks=2,
            cut_window_chunks=1,
        )
        all_segs = []
        for _ in range(5):
            s, _ = seg.feed(_CHUNK, 0.0)
            all_segs.extend(s)
        finals = [s for s in all_segs if s[2]]
        assert len(finals) == 1


class TestReset:
    def test_reset_discards_buffered_speech(self):
        vad = _ScriptedVad(["start", None, None])
        seg = _segmenter(vad)
        for _ in range(2):
            seg.feed(_CHUNK, 0.0)
        seg.reset()
        # After reset, the in-progress utterance is gone; 'end' produces no segment.
        vad2 = _ScriptedVad(["end"])
        seg._vad_iter = vad2
        s, _ = seg.feed(_CHUNK, 0.0)
        assert s == []

    def test_reset_then_new_utterance_works(self):
        vad = _ScriptedVad(["start", "end"])
        seg = _segmenter(vad)
        seg.feed(_CHUNK, 0.0)
        seg.reset()
        vad2 = _ScriptedVad(["start", "end"])
        seg._vad_iter = vad2
        all_segs = []
        for _ in range(2):
            s, _ = seg.feed(_CHUNK, 0.0)
            all_segs.extend(s)
        assert len(all_segs) == 1
