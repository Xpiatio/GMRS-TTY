"""Listen-only safety toggle: with the button checked, every TX path is
short-circuited and the corresponding buttons grey out. The toggle has to
survive a restart (persisted to config.json) so an operator who finishes a
session in RX-only mode comes back up the same way.

These tests pin:
  - the toggle's presence and parentage on the listen strip,
  - the gate on `_transmit_text` / `transmit_id_only` / `_send_preset_phrase`,
  - the Transmit / "This is" / quick-message preset button-enabled mirroring,
  - persistence round-trip via config["listen_only"].
"""
import os
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeMonitor:
    """Inert stand-in for AudioMonitor. Records what it was asked to do rather
    than opening an sd.OutputStream, which raises PortAudioError on a host with
    no audio device — the monitor tests toggle the button, so they would
    otherwise only pass on a machine with a working sound card.
    """

    def __init__(self):
        self.started = []
        self.passthrough = None
        self.muted = None
        self.running = False

    def is_active(self):
        return self.running

    def start(self, device=None):
        self.started.append(device)
        self.running = True

    def stop(self):
        self.running = False

    def push(self, chunk):
        pass

    def set_passthrough(self, enabled):
        self.passthrough = enabled

    def mute(self, muted):
        self.muted = muted


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def __init__(self):
        self.keyed = False

    def key(self):
        self.keyed = True

    def unkey(self):
        self.keyed = False

    def close(self):
        pass


class _WindowHandle:
    """Bundle the constructed MainWindow with the persistence sink and the
    patch contexts so a test can leave the save_json patch active beyond
    construction. Closes the window and unwinds every patch on cleanup."""

    def __init__(self, window, saved, patches):
        self.window = window
        self.saved = saved
        self._patches = patches

    def close(self):
        try:
            self.window.close()
        finally:
            while self._patches:
                self._patches.pop().__exit__(None, None, None)


def _build_window(qapp, initial_listen_only=False, presets=None):
    """Construct a MainWindow with patched persistence and a fake PTT.

    Returns a `_WindowHandle` so the caller can keep the `save_json` patch
    active for the duration of the test — toggling `listen_only` writes
    through `save_json`, and an un-patched fixture would touch the real
    config.json on disk.
    """
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233",
        "name": "Ben",
        "location": "Jenison",
        "filter_profanity": False,
        "voice": "",
        "listen_only": initial_listen_only,
        "quick_messages": list(presets) if presets is not None else [],
    }
    saved = {}

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    def fake_save_json(path, payload):
        saved["payload"] = dict(payload)

    patches = [
        patch.object(mw_mod, "load_json", side_effect=fake_load_json),
        patch.object(mw_mod, "save_json", side_effect=fake_save_json),
        patch("gmrs_tty.config.save_json", side_effect=fake_save_json),
        patch.object(mw_mod, "make_ptt", return_value=_FakePTT()),
        patch.object(mw_mod, "is_online", return_value=True),
    ]
    for p in patches:
        p.__enter__()
    try:
        window = mw_mod.MainWindow()
    except Exception:
        while patches:
            patches.pop().__exit__(None, None, None)
        raise
    # Toggling Monitor starts a real output stream; no test here asserts on the
    # monitor itself, so swap in an inert one and stay device-independent.
    window._monitor = _FakeMonitor()
    return _WindowHandle(window, saved, patches)


@pytest.fixture
def main_window(qapp):
    handle = _build_window(qapp)
    yield handle.window, handle.saved
    handle.close()


class TestListenOnlyToggleSurface:
    def test_button_exists_and_is_checkable(self, main_window):
        window, _ = main_window
        assert hasattr(window, "listen_only_btn")
        assert window.listen_only_btn.isCheckable() is True

    def test_button_lives_on_listen_strip(self, main_window):
        # Should be parented to the normal view — same parentage rules as the
        # Listen button so it's reachable independent of dock state.
        window, _ = main_window
        assert window.listen_only_btn.parentWidget() is window.normal_view

    def test_button_starts_off_when_config_missing(self, main_window):
        window, _ = main_window
        assert window.listen_only_btn.isChecked() is False
        assert window.listen_only is False

    def test_button_keeps_mnemonic(self, main_window):
        # Alt+O activates the toggle; the ampersand has to survive a refactor.
        window, _ = main_window
        text = window.listen_only_btn.text()
        assert "&" in text
        assert "only" in text.lower()


class TestListenOnlyGatesTransmit:
    def test_transmit_text_short_circuits(self, main_window):
        window, _ = main_window
        window.listen_only_btn.setChecked(True)
        with patch.object(window, "_synthesize_and_play") as synth:
            result = window._transmit_text("hello")
        assert result is False
        synth.assert_not_called()

    def test_transmit_id_only_short_circuits(self, main_window):
        window, _ = main_window
        window.listen_only_btn.setChecked(True)
        with patch.object(window, "_synthesize_and_play") as synth:
            window.transmit_id_only()
        synth.assert_not_called()

    def test_send_preset_phrase_short_circuits(self, main_window):
        window, _ = main_window
        window.listen_only_btn.setChecked(True)
        with patch.object(window, "_synthesize_and_play") as synth:
            window._send_preset_phrase("Radio check")
        synth.assert_not_called()

    def test_transmit_text_passes_when_off(self, qapp):
        # Sanity: with listen-only off, the gate doesn't fire and the
        # message reaches _synthesize_and_play. Uses a fresh window so the
        # initial state is unambiguous.
        handle = _build_window(qapp, initial_listen_only=False)
        try:
            window = handle.window
            with patch.object(window, "_synthesize_and_play") as synth:
                result = window._transmit_text("hello")
            assert result is True
            synth.assert_called_once()
        finally:
            handle.close()


class TestListenOnlyDisablesButtons:
    def test_transmit_and_id_buttons_disabled_when_on(self, main_window):
        window, _ = main_window
        window.listen_only_btn.setChecked(True)
        assert window.transmit_btn.isEnabled() is False
        assert window.id_btn.isEnabled() is False

    def test_transmit_and_id_buttons_reenabled_when_off(self, main_window):
        window, _ = main_window
        window.listen_only_btn.setChecked(True)
        window.listen_only_btn.setChecked(False)
        assert window.transmit_btn.isEnabled() is True
        # id_btn re-enables under GMRS (FRS keeps it off); fixture is GMRS.
        assert window.id_btn.isEnabled() is True

    def test_quick_message_buttons_disabled_when_on(self, qapp):
        handle = _build_window(
            qapp, initial_listen_only=False,
            presets=["Radio check", "Standing by"],
        )
        try:
            window = handle.window
            assert len(window._quick_message_buttons) == 2
            for btn in window._quick_message_buttons:
                assert btn.isEnabled() is True
            window.listen_only_btn.setChecked(True)
            for btn in window._quick_message_buttons:
                assert btn.isEnabled() is False
        finally:
            handle.close()

    def test_quick_message_buttons_disabled_at_construction_when_preloaded(self, qapp):
        # An operator who saved listen_only=True should come back up with the
        # presets already greyed out — populate_quick_messages_strip must
        # consult the gate on the very first paint, not just on toggle.
        handle = _build_window(
            qapp, initial_listen_only=True,
            presets=["Radio check"],
        )
        try:
            window = handle.window
            assert window._quick_message_buttons
            for btn in window._quick_message_buttons:
                assert btn.isEnabled() is False
        finally:
            handle.close()


class TestListenOnlyPersistence:
    def test_toggle_writes_config(self, main_window):
        window, saved = main_window
        window.listen_only_btn.setChecked(True)
        assert saved.get("payload", {}).get("listen_only") is True
        window.listen_only_btn.setChecked(False)
        assert saved.get("payload", {}).get("listen_only") is False

    def test_initial_state_reads_config(self, qapp):
        handle = _build_window(qapp, initial_listen_only=True)
        try:
            window = handle.window
            assert window.listen_only is True
            assert window.listen_only_btn.isChecked() is True
            assert window.transmit_btn.isEnabled() is False
            assert window.id_btn.isEnabled() is False
        finally:
            handle.close()


def _fake_stt_worker():
    """Minimal MagicMock that satisfies the stt_worker contract used by
    stop_stt and _on_listen_only_toggled without starting real threads."""
    worker = MagicMock()
    worker.isRunning.return_value = False
    worker.model_cache = None
    return worker


class TestMonitorButtonInteractions:
    """Pin the Listen / Listen Only / Monitor prerequisite chain.

    Rules under test:
      - Monitor is disabled and unchecked at startup.
      - Monitor is only enabled when both Listen (stt_worker present) AND
        Listen Only are active.
      - Turning off Listen Only forces Monitor off (unchecked + disabled).
      - Turning off Listen forces Monitor off (unchecked + disabled).
      - Re-enabling Listen Only after a Listen stop/start cycle correctly
        resumes the Monitor stream via _on_monitor_toggled, not silently
        leaving the button checked-but-inert.
    """

    def test_monitor_btn_starts_disabled_and_unchecked(self, main_window):
        window, _ = main_window
        assert window.monitor_btn.isEnabled() is False
        assert window.monitor_btn.isChecked() is False

    def test_monitor_enabled_only_when_listen_and_listen_only_both_active(
        self, main_window
    ):
        window, _ = main_window
        # Listen Only ON but Listen OFF → monitor must stay disabled.
        window.listen_only_btn.setChecked(True)
        assert window.monitor_btn.isEnabled() is False

    def test_listen_only_off_forces_monitor_unchecked_and_disabled(
        self, main_window
    ):
        window, _ = main_window
        # Simulate Listen active so _on_listen_only_toggled enters the block.
        window.stt_worker = _fake_stt_worker()
        try:
            window.listen_only_btn.setChecked(True)
            # Manually put monitor in the checked+enabled state.
            window.monitor_btn.setEnabled(True)
            window.monitor_btn.setChecked(True)

            window.listen_only_btn.setChecked(False)

            assert window.monitor_btn.isChecked() is False
            assert window.monitor_btn.isEnabled() is False
        finally:
            window.stt_worker = None

    def test_listen_off_forces_monitor_unchecked_and_disabled(
        self, main_window
    ):
        window, _ = main_window
        # Put the window into Listen ON + Listen Only ON + Monitor ON state.
        window.stt_worker = _fake_stt_worker()
        window.listen_only_btn.setChecked(True)
        window.monitor_btn.setEnabled(True)
        window.monitor_btn.setChecked(True)

        # Turning off Listen must leave monitor unchecked AND disabled — not
        # just disabled — so re-enabling Listen Only later fires the monitor
        # toggle correctly.
        window.stop_stt()

        assert window.monitor_btn.isChecked() is False
        assert window.monitor_btn.isEnabled() is False

    def test_monitor_restarts_correctly_after_listen_stop_and_restart(
        self, main_window
    ):
        """Regression: monitor_btn checked+disabled after stop_stt caused
        _on_listen_only_toggled to skip setChecked(True) on re-enable,
        leaving the button visually on but the stream never started."""
        window, _ = main_window
        toggled_on_calls = []
        original = window._on_monitor_toggled

        def spy(checked):
            toggled_on_calls.append(checked)
            original(checked)

        window._on_monitor_toggled = spy
        window.monitor_btn.toggled.connect(spy)

        try:
            # Phase 1: Listen ON → Listen Only ON → Monitor ON.
            window.stt_worker = _fake_stt_worker()
            window.listen_only_btn.setChecked(True)
            window.monitor_btn.setEnabled(True)
            window.monitor_btn.setChecked(True)
            toggled_on_calls.clear()

            # Phase 2: Listen OFF.
            window.stop_stt()
            assert window.monitor_btn.isChecked() is False  # fix guarantee

            # Phase 3: Listen Only OFF (stt_worker already None after stop).
            window.listen_only_btn.setChecked(False)

            # Phase 4: Listen ON again → Listen Only ON again.
            window.stt_worker = _fake_stt_worker()
            window.listen_only_btn.setChecked(True)

            # Monitor button should be enabled and the toggled(True) signal
            # should have fired so the stream would be rewired.
            assert window.monitor_btn.isEnabled() is True
            assert True in toggled_on_calls, (
                "monitor_btn.toggled(True) never fired — "
                "stream would silently not start"
            )
        finally:
            window.stt_worker = None
            window.monitor_btn.toggled.disconnect(spy)
