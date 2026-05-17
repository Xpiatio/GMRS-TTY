"""Light + dark color palettes plus QApplication theming.

The app started as light-only with hex constants in ``gmrs_tty.constants``;
those constants are still re-exported as the light palette so existing
consumers (PDF user-manual builder, tests that pin the verified-checkmark
color) keep working unchanged. New code should prefer ``palette()`` so it
follows the active theme.

Dark-mode colors are drawn from the Tailwind palette at the 400-level so
they meet WCAG AA contrast (≥4.5:1) against the dark window background
(#1F2937). Pills invert: amber-900 background with amber-200 text.
"""
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette


@dataclass(frozen=True)
class Palette:
    """Every theme-sensitive color the UI consumes.

    Names match the historical constants so the diff against the old hex
    literals stays mechanical: a ``COLOR_RX`` reference becomes
    ``palette().rx``, ``PILL_BG`` becomes ``palette().pill_bg``, and so on.
    """
    name: str
    rx: str
    tx: str
    error: str
    warn: str
    pill_bg: str
    pill_text: str
    pill_border: str
    verified: str
    online_online: str
    online_offline: str
    window_bg: str
    window_text: str
    base_bg: str
    header_bg: str
    header_text: str


# Light palette mirrors gmrs_tty.constants exactly. Keeping the values here
# (rather than re-importing) avoids a circular dependency with chat_display.
LIGHT = Palette(
    name="light",
    rx="#15803D",
    tx="#1D4ED8",
    error="#B91C1C",
    warn="#92400E",
    pill_bg="#FEF3C7",
    pill_text="#78350F",
    pill_border="#A16207",
    verified="#15803D",
    online_online="#15803D",
    online_offline="#92400E",
    window_bg="#FFFFFF",
    window_text="#000000",
    base_bg="#FFFFFF",
    header_bg="#F0F0F0",
    header_text="#000000",
)

# Dark palette. Foreground colors at the Tailwind 400 level give ≥4.5:1
# contrast against window_bg (gray-800 #1F2937); the warn/online colors
# match because the same green/amber semantics carry over.
DARK = Palette(
    name="dark",
    rx="#4ADE80",
    tx="#60A5FA",
    error="#F87171",
    warn="#FBBF24",
    pill_bg="#78350F",
    pill_text="#FDE68A",
    pill_border="#FBBF24",
    verified="#4ADE80",
    online_online="#4ADE80",
    online_offline="#FBBF24",
    window_bg="#1F2937",
    window_text="#F9FAFB",
    base_bg="#111827",
    header_bg="#374151",
    header_text="#F9FAFB",
)

_current: Palette = LIGHT


def palette() -> Palette:
    """Return the currently active palette. Read every time a stylesheet is
    built so a later ``set_dark`` toggle takes effect on the next rescan."""
    return _current


def is_dark() -> bool:
    return _current is DARK


def set_dark(dark: bool) -> Palette:
    """Set the active palette and return it. The setter is the single
    write path so tests can patch this module's ``_current`` indirectly
    through the public API."""
    global _current
    _current = DARK if dark else LIGHT
    return _current


def color_remap_light_to_dark() -> dict[str, str]:
    """Light hex → dark hex map for the *text* spans baked into the chat
    document. Used by ChatDisplay.restyle_for_theme to swap RX / TX / WARN /
    ERROR colors on already-rendered lines without re-emitting them.

    Pill spans are handled separately (they get re-applied by
    rescan_all_blocks via the live ``palette()`` lookup), so the pill
    colors are deliberately omitted from this map.
    """
    return {
        LIGHT.rx.lower(): DARK.rx,
        LIGHT.tx.lower(): DARK.tx,
        LIGHT.error.lower(): DARK.error,
        LIGHT.warn.lower(): DARK.warn,
    }


def color_remap_dark_to_light() -> dict[str, str]:
    return {dark.lower(): light for light, dark in color_remap_light_to_dark().items()}


def apply_theme(app, dark: bool) -> Palette:
    """Switch ``app`` to ``dark`` or light and return the active palette.

    Sets a QPalette so every Qt-managed widget (line edits, combo boxes,
    menus, status bar, the chat-widget background) follows the theme
    without per-widget stylesheets. Per-widget stylesheets that hardcode
    colors (header label, pending pills) still need their own update —
    MainWindow handles that after this returns.
    """
    p = set_dark(dark)
    qp = QPalette()
    qp.setColor(QPalette.ColorRole.Window, QColor(p.window_bg))
    qp.setColor(QPalette.ColorRole.WindowText, QColor(p.window_text))
    qp.setColor(QPalette.ColorRole.Base, QColor(p.base_bg))
    qp.setColor(QPalette.ColorRole.AlternateBase, QColor(p.header_bg))
    qp.setColor(QPalette.ColorRole.Text, QColor(p.window_text))
    qp.setColor(QPalette.ColorRole.Button, QColor(p.header_bg))
    qp.setColor(QPalette.ColorRole.ButtonText, QColor(p.window_text))
    qp.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.header_bg))
    qp.setColor(QPalette.ColorRole.ToolTipText, QColor(p.window_text))
    qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.window_text))
    qp.setColor(QPalette.ColorRole.Highlight, QColor(p.tx))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.window_text))
    if app is not None:
        app.setPalette(qp)
    return p


def header_stylesheet() -> str:
    """Stylesheet for the header label. Centralized so the toggle path and
    init both render the same string."""
    p = palette()
    return (
        f"padding: 10px; background-color: {p.header_bg}; "
        f"color: {p.header_text}; border-radius: 5px;"
    )


def pill_stylesheet() -> str:
    """Stylesheet for pending-station pill buttons. Same WCAG goals as the
    chat-display pill spans: ≥4.5:1 text-to-background, distinguishable
    border for non-color cues."""
    p = palette()
    return (
        "QPushButton {"
        f" background-color: {p.pill_bg};"
        f" color: {p.pill_text};"
        f" border: 2px solid {p.pill_border};"
        " padding: 4px 10px; border-radius: 4px;"
        "}"
    )
