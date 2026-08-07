"""The two background loops inside STTWorker, driven directly.

``_transcription_loop`` and ``_final_pass_loop`` are plain methods that run on
threading.Thread, so they can be called synchronously with a pre-seeded queue
and a stub transcriber — no audio device, no model load, no Qt event loop.
"""
import queue
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from gmrs_tty.audio.dsp import make_bandpass_sos
from gmrs_tty.stt.worker import STTWorker

SR = STTWorker.SAMPLE_RATE
# The loops run the real DSP chain; only the Whisper decode is stubbed.
BANDPASS_SOS = make_bandpass_sos(
    SR, STTWorker.BANDPASS_LOW_HZ, STTWorker.BANDPASS_HIGH_HZ
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _worker(qapp, tmp_path, monkeypatch, **kwargs):
    """A worker whose Models/STT is an empty tmp dir (nothing ever loads)."""
    models = tmp_path / "Models" / "STT"
    models.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(STTWorker, "MODELS_STT_DIR", str(models))
    return STTWorker(**kwargs)


def _collect(worker):
    """Record every transcribed_segment emission as a 4-tuple."""
    emitted = []
    worker.transcribed_segment.connect(
        lambda uid, text, is_final, replace: emitted.append((uid, text, is_final, replace))
    )
    return emitted


def _audio(seconds=0.5):
    """Half a second of tone — long enough for the denoise STFT to run."""
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (0.3 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)


def _drain(worker, jobs, transcriber, bandpass_sos=BANDPASS_SOS):
    """Run _transcription_loop over ``jobs`` then the shutdown sentinel."""
    q = queue.Queue()
    for job in jobs:
        q.put(job)
    q.put(None)
    worker._transcription_loop(q, transcriber, bandpass_sos)
    return q


class TestTranscriptionLoop:
    def test_partials_then_final_emit_in_order(self, qapp, tmp_path, monkeypatch):
        w = _worker(qapp, tmp_path, monkeypatch)
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.side_effect = ["hello", "world"]
        _drain(w, [
            (1, _audio(), False, None),
            (1, _audio(), True, None),
        ], transcriber)
        assert emitted == [(1, "hello", False, False), (1, "world", True, False)]

    def test_empty_transcript_emits_nothing(self, qapp, tmp_path, monkeypatch):
        w = _worker(qapp, tmp_path, monkeypatch)
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = None
        _drain(w, [(1, _audio(), False, None)], transcriber)
        assert emitted == []

    def test_transcriber_exception_surfaces_as_error_and_loop_survives(
        self, qapp, tmp_path, monkeypatch
    ):
        w = _worker(qapp, tmp_path, monkeypatch)
        emitted = _collect(w)
        errors = []
        w.error.connect(errors.append)
        transcriber = MagicMock()
        transcriber.transcribe.side_effect = [RuntimeError("decode blew up"), "recovered"]
        _drain(w, [
            (1, _audio(), False, None),
            (2, _audio(), True, None),
        ], transcriber)
        assert any("decode blew up" in e for e in errors)
        assert emitted == [(2, "recovered", True, False)]   # loop kept going

    def test_sentinel_stops_the_loop_before_later_jobs(self, qapp, tmp_path, monkeypatch):
        w = _worker(qapp, tmp_path, monkeypatch)
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "text"
        q = queue.Queue()
        q.put(None)
        q.put((1, _audio(), True, None))
        w._transcription_loop(q, transcriber, BANDPASS_SOS)
        assert emitted == []


class TestTranscriptionLoopWithFinalPass:
    def _final_worker(self, qapp, tmp_path, monkeypatch):
        # An explicit (unstaged) final model is enough to enable the queue —
        # nothing is loaded until _final_pass_loop actually runs.
        return _worker(
            qapp, tmp_path, monkeypatch, whisper_model_final="large-v3-turbo"
        )

    def test_final_segment_is_demoted_and_queued_for_the_final_pass(
        self, qapp, tmp_path, monkeypatch
    ):
        w = self._final_worker(qapp, tmp_path, monkeypatch)
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "fast tail"
        _drain(w, [(1, _audio(), True, None)], transcriber)
        # The fast-path text goes out as a *partial*; the utterance is closed
        # later by the final pass, not here.
        assert emitted == [(1, "fast tail", False, False)]
        uid, audio, _clip = w._final_q.get_nowait()
        assert uid == 1 and audio.size == _audio().size

    def test_over_length_utterance_flushes_as_plain_final(
        self, qapp, tmp_path, monkeypatch
    ):
        w = self._final_worker(qapp, tmp_path, monkeypatch)
        w.final_max_s = 0.05           # below the segment length
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "fast tail"
        _drain(w, [(1, _audio(), True, None)], transcriber)
        assert emitted == [(1, "fast tail", True, False)]
        assert w._final_q.empty()

    def test_noise_clip_travels_with_the_queued_job(self, qapp, tmp_path, monkeypatch):
        w = self._final_worker(qapp, tmp_path, monkeypatch)
        w.noise_profile = True
        # At least NOISE_MIN_S of noise floor, which is what the segmenter
        # guarantees before it hands a clip over — shorter clips are too small
        # for the denoise STFT.
        clip = np.full(int(SR * STTWorker.NOISE_MIN_S), 0.02, dtype=np.float32)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "text"
        _drain(w, [(1, _audio(), True, clip)], transcriber)
        _uid, _audio_out, queued_clip = w._final_q.get_nowait()
        assert queued_clip is clip
        assert w._pending_noise == {}   # handed off, not retained


class TestPendingEviction:
    def test_unfinalized_utterances_are_evicted_with_a_warning(
        self, qapp, tmp_path, monkeypatch, caplog
    ):
        # A TX pause resets the segmenter without emitting a final, so these
        # uids are never popped; without eviction they'd be held all session.
        w = _worker(qapp, tmp_path, monkeypatch, whisper_model_final="large-v3-turbo")
        with caplog.at_level("WARNING"):
            for uid in range(STTWorker.MAX_PENDING_FINAL + 3):
                w._accumulate_for_final(uid, _audio(0.01), _audio(0.01))
        assert len(w._pending_final) == STTWorker.MAX_PENDING_FINAL
        assert len(w._pending_noise) == STTWorker.MAX_PENDING_FINAL
        assert 0 not in w._pending_final            # oldest gone
        assert 0 not in w._pending_noise
        assert w._take_final_audio(STTWorker.MAX_PENDING_FINAL + 2) is not None
        assert any("never finalized" in r.message for r in caplog.records)


class TestFinalPassLoop:
    def _run(self, worker, jobs):
        q = queue.Queue()
        for job in jobs:
            q.put(job)
        q.put(None)
        worker._final_pass_loop(q, BANDPASS_SOS)

    def test_successful_pass_emits_replacing_final(self, qapp, tmp_path, monkeypatch):
        w = _worker(qapp, tmp_path, monkeypatch, whisper_model_final="large-v3-turbo")
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "whole utterance, better"
        monkeypatch.setattr(w, "_load_final_transcriber", lambda: transcriber)
        self._run(w, [(1, _audio(), None)])
        assert emitted == [(1, "whole utterance, better", True, True)]
        # Whole utterance is already squelch-bounded: no VAD re-gating and no
        # confidence drop, or long messages get truncated.
        _args, kwargs = transcriber.transcribe.call_args
        assert kwargs["vad_filter"] is False
        assert kwargs["drop_low_confidence"] is False

    def test_empty_result_still_closes_the_line(self, qapp, tmp_path, monkeypatch):
        w = _worker(qapp, tmp_path, monkeypatch, whisper_model_final="large-v3-turbo")
        emitted = _collect(w)
        transcriber = MagicMock()
        transcriber.transcribe.return_value = ""
        monkeypatch.setattr(w, "_load_final_transcriber", lambda: transcriber)
        self._run(w, [(1, _audio(), None)])
        assert emitted == [(1, "", True, False)]

    def test_transcribe_exception_closes_the_line_and_reports(
        self, qapp, tmp_path, monkeypatch
    ):
        w = _worker(qapp, tmp_path, monkeypatch, whisper_model_final="large-v3-turbo")
        emitted = _collect(w)
        errors = []
        w.error.connect(errors.append)
        transcriber = MagicMock()
        transcriber.transcribe.side_effect = RuntimeError("oom")
        monkeypatch.setattr(w, "_load_final_transcriber", lambda: transcriber)
        self._run(w, [(1, _audio(), None)])
        assert emitted == [(1, "", True, False)]
        assert any("oom" in e for e in errors)

    def test_load_failure_is_attempted_once_then_every_job_closes(
        self, qapp, tmp_path, monkeypatch
    ):
        w = _worker(qapp, tmp_path, monkeypatch, whisper_model_final="large-v3-turbo")
        emitted = _collect(w)
        attempts = []

        def failing_load():
            attempts.append(1)
            return None

        monkeypatch.setattr(w, "_load_final_transcriber", failing_load)
        self._run(w, [(1, _audio(), None), (2, _audio(), None)])
        assert len(attempts) == 1          # not retried per utterance
        assert emitted == [(1, "", True, False), (2, "", True, False)]
