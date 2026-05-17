"""Rolling-waterfall spectrogram widget.

The waterfall is held in a single :class:`QImage` of fixed pixel size.
Each new FFT row is written into a single column at the right edge; on
the next row we scroll the image one column to the left and write again.
This is cheaper than rebuilding the image from a 2-D numpy array on every
paint, and it lines up with the implementation plan's "direct QImage
column-blits" backend choice.

The widget is intentionally self-contained: it owns the colormap LUT,
the dB range, the visible frequency band, and the time-window length.
Settings come in via setters so MainWindow can persist them to
config.json and re-apply on next launch.

Accessibility:
- :meth:`accessibleName` and :meth:`accessibleDescription` summarize the
  current settings (range, window, color map) for screen readers.
- A status text (``current_activity_text``) is updated every time a new
  row arrives, describing the strongest active band — e.g. "Strong
  signal at 1.2 kHz" — so a screen reader announces meaningful changes
  rather than a stream of pixel updates.
- This widget is intentionally NOT the only indicator of an event; the
  chat log already provides a non-visual fallback for any signal that
  produces transcribed speech.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from gmrs_tty.audio.spectrogram import (
    DEFAULT_FRAME_SIZE,
    DEFAULT_SAMPLE_RATE,
    MIN_DB,
    bin_range_for_band,
    frequency_bins,
)
from gmrs_tty.ui import theme
from gmrs_tty.ui.spectro_colormap import (
    AVAILABLE_COLORMAPS,
    DEFAULT_COLORMAP,
    build_lut,
)


# Visible time-window presets. Widget height is fixed; we vary how many
# columns the waterfall image carries, so a longer window means a smaller
# per-row width on screen. 10/30/60 s match the task list in
# implementation_plan.md Stage 14.
TIME_WINDOWS_S = (10, 30, 60)
DEFAULT_TIME_WINDOW_S = 30

# Frequency-range presets: full Nyquist (0–8 kHz at 16 kHz fs) for
# diagnostics like neighbor-channel splatter, or the voice band
# (300–3400 Hz) for the narrowband-FM speech the operator actually cares
# about most of the time.
FREQ_RANGE_FULL = "full"
FREQ_RANGE_VOICE = "voice"
AVAILABLE_FREQ_RANGES = (FREQ_RANGE_VOICE, FREQ_RANGE_FULL)
VOICE_LOW_HZ = 300.0
VOICE_HIGH_HZ = 3400.0

# Sensible dB gain defaults. dB floor = quietest displayable value (black),
# dB ceiling = loudest (top of colormap). Spread chosen so a moderate
# voice signal sits roughly mid-range with the default Hann + 1024 frame.
DEFAULT_DB_FLOOR = -80.0
DEFAULT_DB_CEILING = -20.0

# Pixel height of the waterfall area inside the widget. Kept compact so
# the widget doesn't dominate the main window; the chat log still gets
# the majority of vertical space.
WATERFALL_HEIGHT_PX = 140
# Pixel width reserved for the left-side frequency-axis labels.
AXIS_LABEL_WIDTH_PX = 48
# Pixel height reserved for the bottom time-axis label and overlay marker.
AXIS_LABEL_HEIGHT_PX = 18

# Marker colors for VAD / squelch overlays. Drawn translucent so the
# underlying waterfall stays readable.
MARKER_COLOR_VAD = QColor(255, 255, 255, 140)
MARKER_COLOR_SQUELCH = QColor(255, 235, 100, 120)


@dataclass
class SpectroSettings:
    """Persisted spectrometer settings. Kept as a dataclass so MainWindow
    can round-trip the values through config.json without a custom
    serializer."""
    enabled: bool = False
    colormap: str = DEFAULT_COLORMAP
    freq_range: str = FREQ_RANGE_VOICE
    time_window_s: int = DEFAULT_TIME_WINDOW_S
    db_floor: float = DEFAULT_DB_FLOOR
    db_ceiling: float = DEFAULT_DB_CEILING

    @classmethod
    def from_config(cls, cfg: dict) -> "SpectroSettings":
        section = cfg.get("spectrometer", {}) if isinstance(cfg, dict) else {}
        if not isinstance(section, dict):
            section = {}
        return cls(
            enabled=bool(section.get("enabled", False)),
            colormap=str(section.get("colormap", DEFAULT_COLORMAP))
            if section.get("colormap") in AVAILABLE_COLORMAPS
            else DEFAULT_COLORMAP,
            freq_range=str(section.get("freq_range", FREQ_RANGE_VOICE))
            if section.get("freq_range") in AVAILABLE_FREQ_RANGES
            else FREQ_RANGE_VOICE,
            time_window_s=int(section.get("time_window_s", DEFAULT_TIME_WINDOW_S))
            if section.get("time_window_s") in TIME_WINDOWS_S
            else DEFAULT_TIME_WINDOW_S,
            db_floor=float(section.get("db_floor", DEFAULT_DB_FLOOR)),
            db_ceiling=float(section.get("db_ceiling", DEFAULT_DB_CEILING)),
        )

    def to_config(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "colormap": self.colormap,
            "freq_range": self.freq_range,
            "time_window_s": int(self.time_window_s),
            "db_floor": float(self.db_floor),
            "db_ceiling": float(self.db_ceiling),
        }


class SpectrogramWidget(QWidget):
    """Scrolling waterfall + frequency axis + event markers.

    Owns its own QImage; rows arrive via :meth:`push_row` and are written
    into the rightmost column. Existing pixels scroll left by one column
    per row, giving the classic top-down (or left-to-right, in this case)
    waterfall feel.
    """

    # Emitted with the rendered description string every time the
    # "describe current activity" text changes, so tests / status bars
    # can mirror it without polling.
    activity_text_changed = Signal(str)

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        frame_size: int = DEFAULT_FRAME_SIZE,
        settings: SpectroSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sample_rate = int(sample_rate)
        self.frame_size = int(frame_size)
        self.settings = settings or SpectroSettings()
        self._lut = build_lut(self.settings.colormap)
        self._bin_freqs = frequency_bins(self.frame_size, self.sample_rate)
        self._update_visible_band()
        # Image carries one column per row of spectrogram history; resized
        # whenever the visible band changes (vertical pixels) or the
        # widget itself resizes (horizontal columns of history).
        self._image = QImage(1, 1, QImage.Format.Format_RGB32)
        self._image.fill(Qt.GlobalColor.black)
        self._rows_received = 0
        # Pending overlay markers: list of (column_age, kind). Columns
        # age leftward by one per row; entries past the visible width
        # are dropped on the next push.
        self._markers: list[tuple[int, str]] = []
        self._activity_text = "No signal."
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(WATERFALL_HEIGHT_PX + AXIS_LABEL_HEIGHT_PX)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._refresh_accessible_description()

    # Configuration ------------------------------------------------------
    def apply_settings(self, settings: SpectroSettings) -> None:
        """Replace the active settings and recompute derived state."""
        prev_colormap = self.settings.colormap
        prev_band = (self.settings.freq_range,)
        self.settings = settings
        if settings.colormap != prev_colormap:
            self._lut = build_lut(settings.colormap)
        if (settings.freq_range,) != prev_band:
            self._update_visible_band()
            self._resize_image_to_widget()
        self._refresh_accessible_description()
        self.update()

    def _update_visible_band(self) -> None:
        if self.settings.freq_range == FREQ_RANGE_VOICE:
            lo, hi = bin_range_for_band(
                self.frame_size, self.sample_rate,
                VOICE_LOW_HZ, VOICE_HIGH_HZ,
            )
        else:
            lo, hi = 0, self._bin_freqs.size
        self._bin_lo = lo
        self._bin_hi = hi
        self._visible_bins = self._bin_freqs[lo:hi]

    def _refresh_accessible_description(self) -> None:
        cm = self.settings.colormap
        band = (
            f"voice band {VOICE_LOW_HZ:.0f}–{VOICE_HIGH_HZ:.0f} Hz"
            if self.settings.freq_range == FREQ_RANGE_VOICE
            else f"full band 0–{self.sample_rate // 2} Hz"
        )
        desc = (
            f"Rolling RX waterfall, {band}, "
            f"{self.settings.time_window_s} second window, "
            f"{cm} color map. Use Tab to focus and arrow keys to adjust gain."
        )
        self.setAccessibleName("RX waterfall spectrometer")
        self.setAccessibleDescription(desc)
        self.setToolTip(desc)

    # Sizing / image ownership ------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: D401  (Qt override)
        super().resizeEvent(event)
        self._resize_image_to_widget()

    def _waterfall_rect(self) -> QRect:
        return QRect(
            AXIS_LABEL_WIDTH_PX,
            0,
            max(1, self.width() - AXIS_LABEL_WIDTH_PX),
            WATERFALL_HEIGHT_PX,
        )

    def _resize_image_to_widget(self) -> None:
        rect = self._waterfall_rect()
        cols = max(1, rect.width())
        rows = max(1, self._bin_hi - self._bin_lo)
        new_image = QImage(cols, rows, QImage.Format.Format_RGB32)
        new_image.fill(Qt.GlobalColor.black)
        # Try to preserve history that fits — scale the prior image onto
        # the new one with linear interpolation so a resize doesn't blank
        # the visible context for the operator.
        if (self._image.width() > 1 and self._image.height() > 1
                and self._image.height() == rows):
            painter = QPainter(new_image)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            scaled = self._image.scaled(
                cols, rows,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawImage(0, 0, scaled)
            painter.end()
        self._image = new_image

    # Row ingest ---------------------------------------------------------
    def push_row(self, row: np.ndarray) -> None:
        """Write one FFT row (dB magnitudes, full-spectrum length) into
        the rightmost column after scrolling the image one column left.
        """
        if row is None or row.size == 0:
            return
        if row.size != self._bin_freqs.size:
            # Wrong frame size — drop. Reconfiguring frame_size requires a
            # widget rebuild, not a per-row resize.
            return
        if self._image.height() != (self._bin_hi - self._bin_lo):
            self._resize_image_to_widget()

        visible = row[self._bin_lo: self._bin_hi]
        # Map dB → 0..255 via current floor/ceiling.
        floor = float(self.settings.db_floor)
        ceiling = float(self.settings.db_ceiling)
        if ceiling <= floor:
            ceiling = floor + 1.0
        normalized = (visible - floor) / (ceiling - floor)
        idx = np.clip(np.round(normalized * 255.0), 0, 255).astype(np.uint32)
        # Flip vertically so high frequencies render at the top of the
        # waterfall — the standard convention readers expect.
        idx = idx[::-1]
        column_pixels = self._lut[idx]  # uint32 BGRA per row pixel

        cols = self._image.width()
        rows = self._image.height()
        # Direct buffer scroll-and-write: get a writable uint32 view of
        # the QImage pixels, slide every column one step left, and splat
        # the new column at the rightmost edge. Avoids QImage.scroll
        # (not present in all PySide6 builds) and stays allocation-free
        # past the np.frombuffer wrapper.
        ptr = self._image.bits()
        bpl = self._image.bytesPerLine()
        arr = np.frombuffer(ptr, dtype=np.uint8, count=bpl * rows)
        arr32 = arr.view(np.uint32).reshape(rows, bpl // 4)
        arr32[:, : cols - 1] = arr32[:, 1: cols]
        arr32[:, cols - 1] = column_pixels

        self._rows_received += 1

        # Age existing markers (move left by 1 column) and add new ones
        # at the rightmost column when set externally before this call.
        new_markers: list[tuple[int, str]] = []
        for col, kind in self._markers:
            new_col = col - 1
            if new_col >= 0:
                new_markers.append((new_col, kind))
        self._markers = new_markers

        self._update_activity_text(visible)
        self.update()

    def mark_event(self, kind: str) -> None:
        """Drop a vertical overlay at the current rightmost column.

        Called from MainWindow when STT emits VAD / squelch transitions
        so the operator can correlate the spectrogram with the existing
        capture pipeline.
        """
        if kind not in ("vad_start", "vad_end", "squelch_opened", "squelch_closed"):
            return
        cols = self._image.width()
        # Mark at the rightmost column. ``push_row`` ages the marker
        # leftward on every subsequent row.
        self._markers.append((cols - 1, kind))

    # Activity-text helper ----------------------------------------------
    def _update_activity_text(self, visible_row_db: np.ndarray) -> None:
        ceiling = float(self.settings.db_ceiling)
        floor = float(self.settings.db_floor)
        peak_idx = int(np.argmax(visible_row_db))
        peak_db = float(visible_row_db[peak_idx])
        peak_hz = float(self._visible_bins[peak_idx]) if self._visible_bins.size else 0.0
        if peak_db <= MIN_DB + 1.0 or peak_db <= floor:
            text = "No signal."
        else:
            if peak_db >= ceiling - 6.0:
                level = "Strong"
            elif peak_db >= (floor + ceiling) / 2.0:
                level = "Moderate"
            else:
                level = "Weak"
            if peak_hz >= 1000.0:
                hz_text = f"{peak_hz / 1000.0:.1f} kHz"
            else:
                hz_text = f"{peak_hz:.0f} Hz"
            text = f"{level} signal at {hz_text}"
        if text != self._activity_text:
            self._activity_text = text
            self.activity_text_changed.emit(text)

    @property
    def activity_text(self) -> str:
        return self._activity_text

    # Painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D401  (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())

        rect = self._waterfall_rect()
        # Draw the waterfall image stretched into the widget area. We
        # intentionally use FastTransformation: the smoothing artifacts of
        # bilinear interpolation make narrow peaks (formants, carriers)
        # bleed into neighboring bands and obscure the very thing the
        # widget exists to show.
        painter.drawImage(rect, self._image, QRect(0, 0, self._image.width(), self._image.height()))

        self._draw_freq_axis(painter, rect)
        self._draw_markers(painter, rect)
        self._draw_time_axis(painter, rect)

    def _draw_freq_axis(self, painter: QPainter, rect: QRect) -> None:
        p = theme.palette()
        pen = QPen(QColor(p.window_text))
        pen.setWidth(1)
        painter.setPen(pen)
        font = QFont(self.font())
        font.setPointSize(max(7, font.pointSize() - 2))
        painter.setFont(font)
        if self._visible_bins.size == 0:
            return
        # Five tick marks: top (highest freq), 75 %, 50 %, 25 %, bottom.
        ticks = 5
        for i in range(ticks):
            frac = i / (ticks - 1)
            y = rect.top() + int(frac * (rect.height() - 1))
            # Image is vertically flipped (high freq on top) so frac=0
            # corresponds to the high end of the visible band.
            freq_idx = int(round((1.0 - frac) * (self._visible_bins.size - 1)))
            freq = float(self._visible_bins[freq_idx])
            if freq >= 1000.0:
                label = f"{freq / 1000.0:.1f}k"
            else:
                label = f"{freq:.0f}"
            painter.drawText(
                QRect(0, y - 8, AXIS_LABEL_WIDTH_PX - 4, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.drawLine(
                AXIS_LABEL_WIDTH_PX - 3, y,
                AXIS_LABEL_WIDTH_PX - 1, y,
            )

    def _draw_time_axis(self, painter: QPainter, rect: QRect) -> None:
        p = theme.palette()
        pen = QPen(QColor(p.window_text))
        pen.setWidth(1)
        painter.setPen(pen)
        font = QFont(self.font())
        font.setPointSize(max(7, font.pointSize() - 2))
        painter.setFont(font)
        # Right edge = "now"; left edge = settings.time_window_s seconds ago.
        # Drawn under the waterfall; we don't compute precise tick spacing
        # since the columns-per-second ratio is variable as the widget
        # resizes; instead show the window length explicitly.
        label = f"← {self.settings.time_window_s}s   now →"
        painter.drawText(
            QRect(rect.left(), rect.bottom() + 2, rect.width(), AXIS_LABEL_HEIGHT_PX),
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop,
            label,
        )

    def _draw_markers(self, painter: QPainter, rect: QRect) -> None:
        if not self._markers:
            return
        for col, kind in self._markers:
            if 0 <= col < self._image.width():
                # Translate image-column → on-screen x. Image is stretched
                # to fill rect.width(); use a simple ratio.
                if self._image.width() <= 0:
                    continue
                x = rect.left() + int(col * rect.width() / self._image.width())
                if kind.startswith("vad"):
                    pen = QPen(MARKER_COLOR_VAD)
                else:
                    pen = QPen(MARKER_COLOR_SQUELCH)
                pen.setStyle(Qt.PenStyle.DashLine if kind.endswith(("_end", "_closed"))
                             else Qt.PenStyle.SolidLine)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(QPoint(x, rect.top()), QPoint(x, rect.bottom()))

    # Keyboard interaction ----------------------------------------------
    def keyPressEvent(self, event):
        """Arrow-key gain control: Up/Down nudge dB ceiling, Left/Right
        nudge dB floor by 3 dB per press. Lets keyboard-only operators
        tune the visible contrast without leaving the main window.
        """
        step = 3.0
        s = self.settings
        if event.key() == Qt.Key.Key_Up:
            s.db_ceiling = min(0.0, s.db_ceiling + step)
        elif event.key() == Qt.Key.Key_Down:
            s.db_ceiling = max(s.db_floor + 1.0, s.db_ceiling - step)
        elif event.key() == Qt.Key.Key_Right:
            s.db_floor = min(s.db_ceiling - 1.0, s.db_floor + step)
        elif event.key() == Qt.Key.Key_Left:
            s.db_floor = max(MIN_DB, s.db_floor - step)
        else:
            super().keyPressEvent(event)
            return
        self._refresh_accessible_description()
        self.update()
        event.accept()

    def sizeHint(self) -> QSize:
        return QSize(640, WATERFALL_HEIGHT_PX + AXIS_LABEL_HEIGHT_PX)
