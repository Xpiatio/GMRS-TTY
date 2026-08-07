"""Two-tier final pass: model resolution, backend selection, accumulation,
and backlog handling — no ML models load (everything is stubbed)."""
import queue
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

import gmrs_tty.stt._device as device_mod
import gmrs_tty.stt.gpu_transcriber as gpu_mod
from gmrs_tty.stt.transcriber import WhisperTranscriber
from gmrs_tty.stt.worker import ModelCache, STTWorker

SR = STTWorker.SAMPLE_RATE


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _stage(tmp_path, monkeypatch, *names):
    models = tmp_path / "Models" / "STT"
    models.mkdir(parents=True, exist_ok=True)
    for name in names:
        (models / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(STTWorker, "MODELS_STT_DIR", str(models))
    return models


class TestResolveFinalModel:
    def test_explicit_name_passes_through_even_unstaged(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        w = STTWorker(whisper_model_final="distil-large-v3")
        assert w.whisper_model_final == "distil-large-v3"

    def test_empty_stays_disabled(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        w = STTWorker()
        assert w.whisper_model_final == ""
        assert w._final_q is None

    def test_auto_prefers_turbo(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, "large-v3-turbo", "distil-large-v3")
        w = STTWorker(whisper_model_final="auto")
        assert w.whisper_model_final == "large-v3-turbo"

    def test_auto_skips_fast_path_model(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, "large-v3-turbo", "distil-large-v3")
        w = STTWorker(whisper_model="large-v3-turbo", whisper_model_final="auto")
        assert w.whisper_model_final == "distil-large-v3"

    def test_auto_none_staged_resolves_single_pass(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        w = STTWorker(whisper_model_final="auto")
        assert w.whisper_model_final == ""
        assert w._final_q is None

    def test_auto_gpu_device_accepts_hf_only_staging(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, "large-v3-turbo-hf")
        w = STTWorker(whisper_model_final="auto", stt_final_device="gpu")
        assert w.whisper_model_final == "large-v3-turbo"

    def test_auto_cpu_device_ignores_hf_only_staging(self, qapp, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, "large-v3-turbo-hf")
        w = STTWorker(whisper_model_final="auto", stt_final_device="cpu")
        assert w.whisper_model_final == ""


def _final_worker(qapp, tmp_path, monkeypatch, device="auto"):
    _stage(tmp_path, monkeypatch, "distil-large-v3", "distil-large-v3-hf")
    return STTWorker(whisper_model_final="distil-large-v3", stt_final_device=device)


class TestBackendSelection:
    def test_auto_uses_gpu_when_available(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(device_mod, "rocm_available", lambda: True)
        gpu = MagicMock(name="gpu_inst")
        monkeypatch.setattr(gpu_mod.GpuWhisperTranscriber, "load",
                            classmethod(lambda cls, *a, **k: gpu))
        w = _final_worker(qapp, tmp_path, monkeypatch)
        assert w._load_final_transcriber() is gpu

    def test_auto_uses_cpu_when_no_gpu(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(device_mod, "rocm_available", lambda: False)
        cpu = MagicMock(name="cpu_inst")
        monkeypatch.setattr(WhisperTranscriber, "load",
                            classmethod(lambda cls, *a, **k: cpu))
        w = _final_worker(qapp, tmp_path, monkeypatch)
        assert w._load_final_transcriber() is cpu

    def test_gpu_failure_falls_back_to_cpu(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(device_mod, "rocm_available", lambda: True)

        def boom(cls, *a, **k):
            raise RuntimeError("hip error")

        monkeypatch.setattr(gpu_mod.GpuWhisperTranscriber, "load", classmethod(boom))
        cpu = MagicMock(name="cpu_inst")
        monkeypatch.setattr(WhisperTranscriber, "load",
                            classmethod(lambda cls, *a, **k: cpu))
        w = _final_worker(qapp, tmp_path, monkeypatch)
        errors = []
        w.error.connect(errors.append)
        assert w._load_final_transcriber() is cpu
        assert any("falling back to CPU" in e for e in errors)

    def test_forced_cpu_never_touches_gpu(self, qapp, tmp_path, monkeypatch):
        def explode(cls, *a, **k):
            raise AssertionError("GPU path must not be used")

        monkeypatch.setattr(gpu_mod.GpuWhisperTranscriber, "load", classmethod(explode))
        cpu = MagicMock(name="cpu_inst")
        monkeypatch.setattr(WhisperTranscriber, "load",
                            classmethod(lambda cls, *a, **k: cpu))
        w = _final_worker(qapp, tmp_path, monkeypatch, device="cpu")
        assert w._load_final_transcriber() is cpu

    def test_cached_final_reused_with_fresh_prompt(self, qapp, tmp_path, monkeypatch):
        w = _final_worker(qapp, tmp_path, monkeypatch)
        cached = MagicMock(name="cached_final")
        w._model_cache = ModelCache(
            whisper=MagicMock(), vad_model=MagicMock(), model_name="small.en",
            whisper_final=cached, final_model_name="distil-large-v3",
        )
        w.saved_phrases = ["KE8AAA"]
        assert w._load_final_transcriber() is cached
        cached.update_prompt.assert_called_once_with(["KE8AAA"])


class TestAccumulation:
    def test_accumulate_and_take(self, qapp, tmp_path, monkeypatch):
        w = _final_worker(qapp, tmp_path, monkeypatch)
        a = np.ones(SR, dtype=np.float32)
        w._accumulate_for_final(1, a)
        w._accumulate_for_final(1, a)
        full = w._take_final_audio(1)
        assert full.size == 2 * SR
        assert w._take_final_audio(1) is None  # popped

    def test_over_cap_abandons_pass(self, qapp, tmp_path, monkeypatch):
        w = _final_worker(qapp, tmp_path, monkeypatch)
        w.final_max_s = 1.0
        w._accumulate_for_final(1, np.ones(SR, dtype=np.float32))
        w._accumulate_for_final(1, np.ones(SR, dtype=np.float32))  # over cap
        assert w._take_final_audio(1) is None

    def test_noise_clip_kept_once(self, qapp, tmp_path, monkeypatch):
        w = _final_worker(qapp, tmp_path, monkeypatch)
        clip = np.ones(100, dtype=np.float32)
        w._accumulate_for_final(1, np.ones(10, dtype=np.float32), clip)
        w._accumulate_for_final(1, np.ones(10, dtype=np.float32), clip * 2)
        assert (w._pending_noise[1] == clip).all()


class TestEnqueueBacklog:
    def test_backlog_drops_oldest_and_flushes_it(self, qapp, tmp_path, monkeypatch):
        w = _final_worker(qapp, tmp_path, monkeypatch)
        w._final_q = queue.Queue(maxsize=1)
        emitted = []
        w.transcribed_segment.connect(
            lambda uid, text, fin, rep: emitted.append((uid, text, fin, rep))
        )
        w._enqueue_final(1, np.ones(10, dtype=np.float32))
        w._enqueue_final(2, np.ones(10, dtype=np.float32))
        # Oldest (uid 1) flushed as an empty plain final; uid 2 queued.
        assert emitted == [(1, "", True, False)]
        assert w._final_q.get_nowait()[0] == 2
