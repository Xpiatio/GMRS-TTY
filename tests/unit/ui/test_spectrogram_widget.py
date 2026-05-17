"""Headless tests for the rolling-RX spectrometer widget.

These exercise the parts of SpectrogramWidget that don't need a real
display — settings round-trip, push_row sizing/activity-text, and the
``mark_event`` overlay ledger. The widget is constructed against Qt's
``offscreen`` platform plugin so CI runs without a windowing system.
"""
import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.audio.spectrogram import frequency_bins  # noqa: E402
from gmrs_tty.ui.spectrogram_widget import (  # noqa: E402
    AVAILABLE_FREQ_RANGES,
    DEFAULT_TIME_WINDOW_S,
    FREQ_RANGE_FULL,
    FREQ_RANGE_VOICE,
    SpectrogramWidget,
    SpectroSettings,
    TIME_WINDOWS_S,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _silence_row(frame_size=1024):
    # MIN_DB-equivalent row used to verify the "No signal." text path.
    from gmrs_tty.audio.spectrogram import MIN_DB
    return np.full(frame_size // 2 + 1, MIN_DB, dtype=np.float32)


def _peak_row(peak_bin, frame_size=1024, peak_db=-10.0, floor_db=-120.0):
    row = np.full(frame_size // 2 + 1, floor_db, dtype=np.float32)
    row[peak_bin] = peak_db
    return row


class TestSpectroSettingsRoundTrip:
    def test_default_when_missing(self):
        s = SpectroSettings.from_config({})
        assert s.enabled is False
        assert s.colormap == "viridis"
        assert s.freq_range == FREQ_RANGE_VOICE
        assert s.time_window_s == DEFAULT_TIME_WINDOW_S

    def test_round_trip_preserves_values(self):
        cfg = {"spectrometer": {
            "enabled": True, "colormap": "grayscale",
            "freq_range": FREQ_RANGE_FULL, "time_window_s": 60,
            "db_floor": -90.0, "db_ceiling": -10.0,
        }}
        s = SpectroSettings.from_config(cfg)
        assert s.to_config() == cfg["spectrometer"]

    def test_unknown_colormap_falls_back(self):
        s = SpectroSettings.from_config({"spectrometer": {"colormap": "nope"}})
        assert s.colormap == "viridis"

    def test_unknown_freq_range_falls_back(self):
        s = SpectroSettings.from_config(
            {"spectrometer": {"freq_range": "ultraviolet"}}
        )
        assert s.freq_range == FREQ_RANGE_VOICE

    def test_unknown_time_window_falls_back(self):
        s = SpectroSettings.from_config(
            {"spectrometer": {"time_window_s": 7}}
        )
        assert s.time_window_s == DEFAULT_TIME_WINDOW_S

    def test_garbage_section_falls_back(self):
        s = SpectroSettings.from_config({"spectrometer": "not a dict"})
        assert s.enabled is False


class TestWidgetConstruction:
    def test_constructs_with_defaults(self, qapp):
        w = SpectrogramWidget()
        try:
            assert w.minimumHeight() > 0
            assert w.accessibleName() == "RX waterfall spectrometer"
            assert "voice band" in w.accessibleDescription().lower()
        finally:
            w.deleteLater()

    def test_full_band_description(self, qapp):
        w = SpectrogramWidget(
            settings=SpectroSettings(freq_range=FREQ_RANGE_FULL),
        )
        try:
            assert "full band" in w.accessibleDescription().lower()
        finally:
            w.deleteLater()


class TestPushRow:
    def test_silence_row_sets_no_signal_text(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(640, 200)
            w.push_row(_silence_row())
            assert w.activity_text == "No signal."
        finally:
            w.deleteLater()

    def test_peak_row_in_voice_band_announces_kilohertz(self, qapp):
        w = SpectrogramWidget(settings=SpectroSettings(freq_range=FREQ_RANGE_VOICE))
        try:
            w.resize(640, 200)
            sr = w.sample_rate
            n = w.frame_size
            # Place a peak at exactly 1500 Hz.
            target_bin = int(round(1500.0 * n / sr))
            w.push_row(_peak_row(target_bin, frame_size=n, peak_db=-15.0))
            assert "kHz" in w.activity_text
            assert "signal" in w.activity_text.lower()
        finally:
            w.deleteLater()

    def test_wrong_length_row_ignored(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(640, 200)
            initial = w.activity_text
            w.push_row(np.zeros(7, dtype=np.float32))
            assert w.activity_text == initial
        finally:
            w.deleteLater()

    def test_empty_row_ignored(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(640, 200)
            initial = w.activity_text
            w.push_row(np.zeros(0, dtype=np.float32))
            w.push_row(None)
            assert w.activity_text == initial
        finally:
            w.deleteLater()


class TestMarkers:
    def test_mark_event_recorded(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(640, 200)
            # Force the QImage to pick up the new widget size; offscreen
            # platform doesn't always fire resizeEvent on .resize() alone.
            w._resize_image_to_widget()
            w.mark_event("vad_start")
            assert any(kind == "vad_start" for _, kind in w._markers)
        finally:
            w.deleteLater()

    def test_unknown_kind_ignored(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(640, 200)
            before = len(w._markers)
            w.mark_event("not_a_real_event")
            assert len(w._markers) == before
        finally:
            w.deleteLater()

    def test_markers_age_left_per_row(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(640, 200)
            # Force the QImage to pick up the new widget size; offscreen
            # platform doesn't always fire resizeEvent on .resize() alone.
            w._resize_image_to_widget()
            w.mark_event("vad_start")
            initial_col = w._markers[-1][0]
            w.push_row(_silence_row())
            assert w._markers[-1][0] == initial_col - 1
        finally:
            w.deleteLater()

    def test_marker_drops_after_traveling_off_image(self, qapp):
        w = SpectrogramWidget()
        try:
            w.resize(100, 200)  # narrow → marker exits quickly
            w.mark_event("vad_start")
            for _ in range(w._image.width() + 5):
                w.push_row(_silence_row())
            assert w._markers == []
        finally:
            w.deleteLater()


class TestApplySettings:
    def test_colormap_change_rebuilds_lut(self, qapp):
        w = SpectrogramWidget(settings=SpectroSettings(colormap="viridis"))
        try:
            before = w._lut.copy()
            w.apply_settings(SpectroSettings(colormap="grayscale"))
            assert not np.array_equal(before, w._lut)
        finally:
            w.deleteLater()

    def test_freq_range_change_updates_visible_band(self, qapp):
        w = SpectrogramWidget(settings=SpectroSettings(freq_range=FREQ_RANGE_VOICE))
        try:
            voice_bins = w._bin_hi - w._bin_lo
            w.apply_settings(SpectroSettings(freq_range=FREQ_RANGE_FULL))
            full_bins = w._bin_hi - w._bin_lo
            assert full_bins > voice_bins
        finally:
            w.deleteLater()


class TestKeyboardGainControl:
    def test_up_arrow_raises_ceiling(self, qapp):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        w = SpectrogramWidget()
        try:
            before = w.settings.db_ceiling
            ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
            w.keyPressEvent(ev)
            assert w.settings.db_ceiling > before or w.settings.db_ceiling == 0.0
        finally:
            w.deleteLater()

    def test_down_arrow_lowers_ceiling_but_not_below_floor(self, qapp):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        w = SpectrogramWidget(
            settings=SpectroSettings(db_floor=-50.0, db_ceiling=-48.0)
        )
        try:
            ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
            w.keyPressEvent(ev)
            assert w.settings.db_ceiling > w.settings.db_floor
        finally:
            w.deleteLater()


class TestPresetConstants:
    def test_time_windows_match_plan(self):
        # implementation_plan.md Stage 14 calls out 10/30/60 s presets;
        # if someone changes them, the docs need to change too.
        assert TIME_WINDOWS_S == (10, 30, 60)

    def test_freq_ranges_cover_voice_and_full(self):
        assert FREQ_RANGE_VOICE in AVAILABLE_FREQ_RANGES
        assert FREQ_RANGE_FULL in AVAILABLE_FREQ_RANGES


class TestFrequencyBinsRoundtrip:
    def test_voice_visible_bins_within_voice_band(self):
        # Sanity: the precomputed visible_bins slice for voice mode really
        # does cover only ~300–3400 Hz, not the full Nyquist range.
        from gmrs_tty.ui.spectrogram_widget import VOICE_HIGH_HZ, VOICE_LOW_HZ

        w = SpectrogramWidget(settings=SpectroSettings(freq_range=FREQ_RANGE_VOICE))
        try:
            vb = w._visible_bins
            assert vb[0] >= VOICE_LOW_HZ - 50
            assert vb[-1] <= VOICE_HIGH_HZ + 50
        finally:
            w.deleteLater()

    def test_full_visible_bins_reach_nyquist(self):
        w = SpectrogramWidget(settings=SpectroSettings(freq_range=FREQ_RANGE_FULL))
        try:
            assert w._visible_bins[-1] >= w.sample_rate / 2 - 50
        finally:
            w.deleteLater()
