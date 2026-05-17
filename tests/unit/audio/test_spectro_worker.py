"""Smoke test for the FFT QThread worker.

The worker is a thin wrapper over :class:`ChunkRing` and
:func:`compute_frame` — both are covered separately — so this file
only verifies that pushing audio onto a live thread eventually emits a
row of the right shape on the Qt signal.

Skipped without Qt; uses the offscreen platform plugin so it stays
display-independent.
"""
import os
import threading

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.audio.spectro_worker import SpectrogramWorker  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    # Use QApplication (not QCoreApplication) so this test coexists with
    # other Qt-dependent tests in the suite — Qt forbids mixing the two
    # within a single process and the first to call .instance() wins.
    return QApplication.instance() or QApplication([])


class TestWorkerRoundTrip:
    def test_push_produces_row_of_expected_length(self, qapp):
        worker = SpectrogramWorker(sample_rate=16000, frame_size=256, hop_size=128)
        received = []
        done = threading.Event()

        def on_row(row):
            received.append(row)
            done.set()

        worker.row_ready.connect(on_row)
        worker.start()
        try:
            worker.push_chunk(np.zeros(512, dtype=np.float32))
            # Spin the Qt event loop until the queued slot fires, with a
            # hard timeout so a misbehaving worker can't hang the suite.
            for _ in range(200):
                qapp.processEvents()
                if received:
                    break
                done.wait(0.01)
            assert received, "worker must emit at least one row"
            assert received[0].shape[0] == 256 // 2 + 1
            assert received[0].dtype == np.float32
        finally:
            worker.stop()
            worker.wait(2000)

    def test_garbage_chunk_is_ignored(self, qapp):
        worker = SpectrogramWorker(sample_rate=16000, frame_size=64, hop_size=32)
        received = []
        worker.row_ready.connect(received.append)
        worker.start()
        try:
            worker.push_chunk(None)
            worker.push_chunk("not an array")
            worker.push_chunk(np.zeros(0, dtype=np.float32))
            for _ in range(20):
                qapp.processEvents()
            assert received == []
        finally:
            worker.stop()
            worker.wait(2000)
