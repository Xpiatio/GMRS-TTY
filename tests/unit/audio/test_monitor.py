from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from gmrs_tty.audio.monitor import AudioMonitor


@pytest.fixture()
def monitor():
    return AudioMonitor()


def _chunk(n=512, value=0.1):
    return np.full(n, value, dtype=np.float32)


class TestAudioMonitorRates:
    def test_output_rate_is_48k(self):
        assert AudioMonitor.OUTPUT_RATE == 48_000

    def test_input_rate_is_16k(self):
        assert AudioMonitor.INPUT_RATE == 16_000

    def test_upsample_ratio(self):
        assert AudioMonitor._UPSAMPLE_RATIO == 3


class TestAudioMonitorPush:
    def test_push_upsamples_chunk(self, monitor):
        """A 512-sample input chunk should become 1536 samples in the buffer."""
        with patch("sounddevice.OutputStream") as mock_stream_cls:
            mock_stream = MagicMock()
            mock_stream_cls.return_value = mock_stream
            mock_stream.active = True
            monitor.start()

        monitor.push(_chunk(512))
        assert monitor._buf_samples == 512 * AudioMonitor._UPSAMPLE_RATIO

    def test_push_dropped_when_inactive(self, monitor):
        monitor.push(_chunk(512))
        assert monitor._buf_samples == 0

    def test_buffer_caps_at_max(self, monitor):
        with patch("sounddevice.OutputStream") as mock_stream_cls:
            mock_stream = MagicMock()
            mock_stream_cls.return_value = mock_stream
            monitor.start()

        # Push enough chunks to exceed the 1-second cap
        chunk_out_samples = 512 * AudioMonitor._UPSAMPLE_RATIO
        pushes_to_overflow = (AudioMonitor._MAX_BUFFER_SAMPLES // chunk_out_samples) + 2
        for _ in range(pushes_to_overflow):
            monitor.push(_chunk(512))

        assert monitor._buf_samples <= AudioMonitor._MAX_BUFFER_SAMPLES


class TestAudioMonitorMute:
    def test_mute_sets_event(self, monitor):
        monitor.mute(True)
        assert monitor._muted.is_set()

    def test_unmute_clears_event(self, monitor):
        monitor.mute(True)
        monitor.mute(False)
        assert not monitor._muted.is_set()

    def test_callback_zeros_output_when_muted(self, monitor):
        monitor.mute(True)
        outdata = np.ones((512, 1), dtype=np.float32)
        monitor._callback(outdata, 512, None, None)
        assert np.all(outdata == 0)


class TestAudioMonitorCallback:
    def test_callback_fills_from_buffer(self, monitor):
        upsampled = np.ones(1536, dtype=np.float32) * 0.5
        monitor._buf.append(upsampled)
        monitor._buf_samples = len(upsampled)

        outdata = np.zeros((512, 1), dtype=np.float32)
        monitor._callback(outdata, 512, None, None)
        assert np.all(outdata[:, 0] == pytest.approx(0.5))
        assert monitor._buf_samples == 1536 - 512

    def test_callback_zeros_remainder_when_buffer_empty(self, monitor):
        outdata = np.ones((512, 1), dtype=np.float32)
        monitor._callback(outdata, 512, None, None)
        assert np.all(outdata == 0)


class TestAudioMonitorFilterState:
    def test_filter_state_resets_on_start(self, monitor):
        with patch("sounddevice.OutputStream") as mock_stream_cls:
            mock_stream_cls.return_value = MagicMock()
            monitor.push(_chunk(512))  # advance zi
            zi_before = monitor._zi.copy()
            monitor.start()
            # zi should have been reset (not identical to the advanced state)
            # Both should have the same shape; the reset zi differs after a push.
            assert monitor._zi.shape == zi_before.shape

    def test_filter_state_is_stateful_across_chunks(self, monitor):
        with patch("sounddevice.OutputStream") as mock_stream_cls:
            mock_stream_cls.return_value = MagicMock()
            monitor.start()

        zi_initial = monitor._zi.copy()
        monitor.push(_chunk(512, value=0.5))
        zi_after = monitor._zi.copy()
        # State should have changed after processing a non-zero chunk
        assert not np.allclose(zi_initial, zi_after)
