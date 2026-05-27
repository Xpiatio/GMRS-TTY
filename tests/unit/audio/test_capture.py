"""Unit tests for SystemMonitorSource, enumerate_monitor_sources, and AudioInputSource."""
import sys
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from gmrs_tty.audio.capture import (
    AudioInputSource,
    ParecSource,
    PortAudioSource,
    SystemMonitorSource,
    enumerate_monitor_sources,
    open_input_source,
)


# ---------------------------------------------------------------------------
# enumerate_monitor_sources
# ---------------------------------------------------------------------------

class TestEnumerateMonitorSourcesLinux:
    @pytest.fixture(autouse=True)
    def _patch_platform(self, monkeypatch):
        monkeypatch.setattr("gmrs_tty.audio.capture.sys.platform", "linux")

    def test_always_includes_system_default(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            sources = enumerate_monitor_sources()
        assert sources[0] == ("System Default", "")

    def test_parses_pactl_sink_names(self):
        pactl_output = (
            "0\talsa_output.pci-0000.analog-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
            "1\talsa_output.hdmi-stereo\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=pactl_output, returncode=0)
            sources = enumerate_monitor_sources()
        names = [s[1] for s in sources]
        assert "alsa_output.pci-0000.analog-stereo" in names
        assert "alsa_output.hdmi-stereo" in names

    def test_returns_default_only_on_subprocess_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            sources = enumerate_monitor_sources()
        assert sources == [("System Default", "")]

    def test_sink_display_name_equals_sink_id(self):
        pactl_output = "0\tmy_sink\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=pactl_output, returncode=0)
            sources = enumerate_monitor_sources()
        assert ("my_sink", "my_sink") in sources


class TestEnumerateMonitorSourcesWindows:
    @pytest.fixture(autouse=True)
    def _patch_platform(self, monkeypatch):
        monkeypatch.setattr("gmrs_tty.audio.capture.sys.platform", "win32")

    def test_lists_output_devices(self):
        fake_devices = [
            {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Microphone", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "HDMI Output", "max_input_channels": 0, "max_output_channels": 2},
        ]
        with patch("sounddevice.query_devices", return_value=fake_devices):
            sources = enumerate_monitor_sources()
        sink_ids = [s[1] for s in sources]
        assert "0" in sink_ids   # Speakers
        assert "2" in sink_ids   # HDMI Output
        assert "1" not in sink_ids  # Microphone is input-only

    def test_always_includes_system_default(self):
        with patch("sounddevice.query_devices", return_value=[]):
            sources = enumerate_monitor_sources()
        assert sources[0] == ("System Default", "")

    def test_returns_default_only_on_error(self):
        with patch("sounddevice.query_devices", side_effect=RuntimeError):
            sources = enumerate_monitor_sources()
        assert sources == [("System Default", "")]


# ---------------------------------------------------------------------------
# SystemMonitorSource — Linux path
# ---------------------------------------------------------------------------

class TestSystemMonitorSourceLinux:
    @pytest.fixture(autouse=True)
    def _patch_platform(self, monkeypatch):
        monkeypatch.setattr("gmrs_tty.audio.capture.sys.platform", "linux")

    def _make_source(self, sink="sink_name", proc=None):
        src = SystemMonitorSource.__new__(SystemMonitorSource)
        src._sample_rate = 16000
        src._chunk_samples = 512
        src._bytes_per_chunk = 1024
        src._proc = proc or MagicMock()
        src._stream = None
        return src

    def test_open_linux_uses_named_sink_monitor(self):
        with patch("shutil.which", return_value="/usr/bin/parec"), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            src = SystemMonitorSource(16000, 512, sink="my_sink")
        cmd = mock_popen.call_args[0][0]
        assert "--device=my_sink.monitor" in cmd
        src.close()

    def test_open_linux_queries_default_sink_when_none_given(self):
        with patch("shutil.which", return_value="/usr/bin/parec"), \
             patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen:
            mock_run.return_value = MagicMock(stdout="default_sink\n", returncode=0)
            mock_popen.return_value = MagicMock()
            src = SystemMonitorSource(16000, 512, sink="")
        cmd = mock_popen.call_args[0][0]
        assert "--device=default_sink.monitor" in cmd
        src.close()

    def test_open_linux_raises_when_parec_missing(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="parec"):
                SystemMonitorSource(16000, 512)

    def test_read_decodes_int16_to_float32(self):
        src = self._make_source()
        raw_int16 = np.array([0, 32767, -32768, 16384], dtype=np.int16)
        src._proc.stdout.read.return_value = raw_int16.tobytes()
        src._bytes_per_chunk = len(raw_int16.tobytes())
        result = src.read()
        assert result.dtype == np.float32
        assert result[1] == pytest.approx(32767 / 32768.0)

    def test_read_raises_on_closed_stream(self):
        src = self._make_source()
        src._proc.stdout.read.return_value = b""
        with pytest.raises(IOError, match="closed unexpectedly"):
            src.read()

    def test_close_terminates_proc(self):
        proc = MagicMock()
        src = self._make_source(proc=proc)
        src.close()
        proc.terminate.assert_called_once()

    def test_close_is_idempotent(self):
        src = self._make_source()
        src.close()
        src.close()  # should not raise


# ---------------------------------------------------------------------------
# SystemMonitorSource — Windows path
# ---------------------------------------------------------------------------

class TestSystemMonitorSourceWindows:
    @pytest.fixture(autouse=True)
    def _patch_platform(self, monkeypatch):
        monkeypatch.setattr("gmrs_tty.audio.capture.sys.platform", "win32")

    def _make_source_with_stream(self, stream=None):
        src = SystemMonitorSource.__new__(SystemMonitorSource)
        src._sample_rate = 16000
        src._chunk_samples = 512
        src._bytes_per_chunk = 1024
        src._proc = None
        src._stream = stream or MagicMock()
        return src

    def test_open_windows_uses_wasapi_loopback(self):
        import sounddevice as sd
        mock_settings = MagicMock()
        mock_stream = MagicMock()
        mock_wasapi_cls = MagicMock(return_value=mock_settings)
        mock_istream_cls = MagicMock(return_value=mock_stream)
        with patch.object(sd, "WasapiSettings", mock_wasapi_cls, create=True), \
             patch.object(sd, "InputStream", mock_istream_cls, create=True):
            src = SystemMonitorSource(16000, 512, sink="3")
            mock_istream_cls.assert_called_once()
            call_kwargs = mock_istream_cls.call_args[1]
            assert call_kwargs["device"] == 3
            assert call_kwargs["extra_settings"] is mock_settings
        src.close()

    def test_open_windows_raises_without_wasapi_settings(self):
        # WasapiSettings doesn't exist on non-Windows builds → RuntimeError
        with patch("gmrs_tty.audio.capture.hasattr", return_value=False):
            with pytest.raises(RuntimeError, match="WASAPI"):
                SystemMonitorSource(16000, 512)

    def test_read_returns_float32_mono(self):
        src = self._make_source_with_stream()
        fake_data = np.zeros((512, 1), dtype=np.float32)
        fake_data[0, 0] = 0.5
        src._stream.read.return_value = (fake_data, None)
        result = src.read()
        assert result.shape == (512,)
        assert result[0] == pytest.approx(0.5)

    def test_close_stops_stream(self):
        stream = MagicMock()
        src = self._make_source_with_stream(stream=stream)
        src.close()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()


# ---------------------------------------------------------------------------
# open_input_source routing
# ---------------------------------------------------------------------------

class TestOpenInputSourceRouting:
    def test_system_monitor_returns_system_monitor_source(self):
        with patch("gmrs_tty.audio.capture.SystemMonitorSource") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = open_input_source(16000, 512, input_device="system_monitor", system_monitor_sink="my_sink")
        mock_cls.assert_called_once_with(16000, 512, sink="my_sink")

    def test_none_device_tries_parec_first(self):
        with patch("gmrs_tty.audio.capture.ParecSource") as mock_parec:
            mock_parec.return_value = MagicMock()
            open_input_source(16000, 512, input_device=None)
        mock_parec.assert_called_once()

    def test_none_device_falls_back_to_portaudio_when_parec_missing(self):
        with patch("gmrs_tty.audio.capture.ParecSource", side_effect=FileNotFoundError), \
             patch("gmrs_tty.audio.capture.PortAudioSource") as mock_pa:
            mock_pa.return_value = MagicMock()
            open_input_source(16000, 512, input_device=None)
        mock_pa.assert_called_once()


# ---------------------------------------------------------------------------
# AudioInputSource Protocol conformance
# ---------------------------------------------------------------------------

class TestAudioInputSourceProtocol:
    def _make_system_monitor_source(self):
        src = SystemMonitorSource.__new__(SystemMonitorSource)
        src._proc = MagicMock()
        src._stream = None
        src._bytes_per_chunk = 1024
        src._chunk_samples = 512
        return src

    def _make_parec_source(self):
        src = ParecSource.__new__(ParecSource)
        src.proc = MagicMock()
        src.bytes_per_chunk = 1024
        return src

    def _make_portaudio_source(self):
        src = PortAudioSource.__new__(PortAudioSource)
        src.stream = MagicMock()
        src.chunk_samples = 512
        return src

    def test_system_monitor_source_satisfies_protocol(self):
        assert isinstance(self._make_system_monitor_source(), AudioInputSource)

    def test_parec_source_satisfies_protocol(self):
        assert isinstance(self._make_parec_source(), AudioInputSource)

    def test_portaudio_source_satisfies_protocol(self):
        assert isinstance(self._make_portaudio_source(), AudioInputSource)
