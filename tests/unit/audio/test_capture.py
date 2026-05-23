"""Unit tests for YouTubeSource._resolve_audio_url."""
from unittest.mock import MagicMock, patch

import pytest

from gmrs_tty.audio.capture import YouTubeSource


def _make_run_result(stdout="", stderr="", returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


@pytest.fixture(autouse=True)
def _patch_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/fake")


@pytest.fixture(autouse=True)
def _no_start(monkeypatch):
    monkeypatch.setattr(YouTubeSource, "_start", lambda self: None)


class TestResolveAudioUrl:
    def _make_source(self):
        src = YouTubeSource.__new__(YouTubeSource)
        src._url = "https://www.youtube.com/watch?v=TEST"
        src._sample_rate = 16000
        src._chunk_samples = 512
        src._bytes_per_chunk = 512 * 4
        src._proc = None
        return src

    def test_returns_url_on_first_format(self):
        src = self._make_source()
        ok = _make_run_result(stdout="https://cdn.example.com/audio.webm\n")
        with patch("subprocess.run", return_value=ok) as mock_run:
            url = src._resolve_audio_url()
        assert url == "https://cdn.example.com/audio.webm"
        assert mock_run.call_count == 1
        args = mock_run.call_args[0][0]
        assert "-f" in args
        assert args[args.index("-f") + 1] == "bestaudio"

    def test_falls_back_to_second_format(self):
        src = self._make_source()
        fail = _make_run_result(stdout="", stderr="some warning", returncode=1)
        ok = _make_run_result(stdout="https://cdn.example.com/audio.mp4\n")
        with patch("subprocess.run", side_effect=[fail, ok]) as mock_run:
            url = src._resolve_audio_url()
        assert url == "https://cdn.example.com/audio.mp4"
        assert mock_run.call_count == 2
        formats_tried = [
            c[0][0][c[0][0].index("-f") + 1] for c in mock_run.call_args_list
        ]
        assert formats_tried == ["bestaudio", "bestaudio/best"]

    def test_raises_io_error_when_both_formats_fail(self):
        src = self._make_source()
        fail1 = _make_run_result(stdout="", stderr="bot detection triggered", returncode=1)
        fail2 = _make_run_result(stdout="", stderr="Sign in to confirm", returncode=1)
        with patch("subprocess.run", side_effect=[fail1, fail2]):
            with pytest.raises(IOError) as exc_info:
                src._resolve_audio_url()
        assert src._url in str(exc_info.value)
        assert "Sign in to confirm" in str(exc_info.value)

    def test_error_includes_stderr_of_last_attempt(self):
        src = self._make_source()
        fail = _make_run_result(stdout="", stderr="ERROR: age restricted", returncode=1)
        with patch("subprocess.run", return_value=fail):
            with pytest.raises(IOError) as exc_info:
                src._resolve_audio_url()
        assert "age restricted" in str(exc_info.value)

    def test_error_without_stderr_is_still_readable(self):
        src = self._make_source()
        fail = _make_run_result(stdout="", stderr="", returncode=1)
        with patch("subprocess.run", return_value=fail):
            with pytest.raises(IOError) as exc_info:
                src._resolve_audio_url()
        msg = str(exc_info.value)
        assert src._url in msg
        assert "no audio URL" in msg
