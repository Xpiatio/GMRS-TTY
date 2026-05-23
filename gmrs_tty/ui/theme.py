"""Light + dark color palettes plus QApplication theming.

The app started as light-only with hex constants in ``gmrs_tty.constants``;
those constants are still re-exported as the light palette so existing
consumers (PDF user-manual builder, tests that pin the verified-checkmark
color) keep working unchanged. New code should prefer ``palette()`` so it
follows the active theme.

Dark-mode colors are drawn from the Tailwind palette at the 400-level so
they meet WCAG AA contrast (≥4.5:1) against the dark window background
(#1F2937). Pending pills use amber-200 text on amber-900 background; the
``warn`` role uses an orange ramp so a warn-state chat line never reads
as the same color as a pending-station pill border (audit F-001).
"""
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


# Spacing tokens (px). Audit F-004 — every layout spacing / stylesheet padding
# value should reference one of these so the visual rhythm stays uniform.
SPACING_XS = 4
SPACING_S = 8
SPACING_M = 12
SPACING_L = 16


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
    pill_hover_bg: str
    verified: str
    online_online: str
    online_offline: str
    window_bg: str
    window_text: str
    base_bg: str
    header_bg: str
    header_border: str
    header_text: str
    focus_ring: str
    dock_title_bg: str
    dock_title_text: str
    placeholder_text: str


# Light palette mirrors gmrs_tty.constants exactly for the legacy roles.
# F-001: warn shifts to an orange ramp so it no longer matches the pending-
# pill amber border in either theme.
# F-009: header_bg darkens from #F0F0F0 to #E5E7EB for stronger separation
# from #FFFFFF window background.
LIGHT = Palette(
    name="light",
    rx="#15803D",
    tx="#1D4ED8",
    error="#B91C1C",
    warn="#C2410B",
    pill_bg="#FEF3C7",
    pill_text="#78350F",
    pill_border="#A16207",
    pill_hover_bg="#FDE68A",
    verified="#15803D",
    online_online="#15803D",
    online_offline="#C2410B",
    window_bg="#FFFFFF",
    window_text="#000000",
    base_bg="#FFFFFF",
    header_bg="#E5E7EB",
    header_border="#D1D5DB",
    header_text="#000000",
    focus_ring="#1D4ED8",
    dock_title_bg="#E5E7EB",
    dock_title_text="#111827",
    placeholder_text="#6B7280",
)

# Dark palette. Foreground colors at the Tailwind 400 level give ≥4.5:1
# contrast against window_bg (gray-800 #1F2937). F-001: warn moves to
# orange-400 #FB923C so pending-pill amber (#FBBF24) and warning text are
# visually distinct.
DARK = Palette(
    name="dark",
    rx="#4ADE80",
    tx="#60A5FA",
    error="#F87171",
    warn="#FB923C",
    pill_bg="#78350F",
    pill_text="#FDE68A",
    pill_border="#FBBF24",
    pill_hover_bg="#92400E",
    verified="#4ADE80",
    online_online="#4ADE80",
    online_offline="#FB923C",
    window_bg="#1F2937",
    window_text="#F9FAFB",
    base_bg="#111827",
    header_bg="#374151",
    header_border="#4B5563",
    header_text="#F9FAFB",
    focus_ring="#60A5FA",
    dock_title_bg="#374151",
    dock_title_text="#F9FAFB",
    placeholder_text="#9CA3AF",
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
    colors (header label, pending pills, dock title bars) still need
    their own update — MainWindow handles that after this returns.
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
    # F-012: placeholders need to read as muted vs typed text. The old
    # mapping (PlaceholderText = window_text) made them indistinguishable.
    qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.placeholder_text))
    qp.setColor(QPalette.ColorRole.Highlight, QColor(p.tx))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.window_text))
    if app is not None:
        app.setPalette(qp)
    return p


# Typography helpers. F-005: every custom font flows through one of these
# so the relationship between roles is explicit and OS font-scale carries
# through (we only ever bump point-size deltas, never set absolute sizes).
def _base_font() -> QFont:
    app = QApplication.instance()
    return QFont(app.font()) if app is not None else QFont()


def font_body() -> QFont:
    return _base_font()


def font_emphasis() -> QFont:
    f = _base_font()
    f.setBold(True)
    return f


def font_header() -> QFont:
    f = _base_font()
    f.setBold(True)
    f.setPointSize(f.pointSize() + 2)
    return f


def font_chat() -> QFont:
    """Chat display body font: +2pt above OS default for ADA legibility."""
    f = _base_font()
    f.setPointSize(f.pointSize() + 2)
    return f


def font_icon() -> QFont:
    f = _base_font()
    f.setPointSize(f.pointSize() + 4)
    return f


def header_stylesheet() -> str:
    """Stylesheet for the header label. Centralized so the toggle path and
    init both render the same string."""
    p = palette()
    return (
        f"padding: {SPACING_M}px; background-color: {p.header_bg}; "
        f"color: {p.header_text}; border: 1px solid {p.header_border}; "
        "border-radius: 5px;"
    )


def chat_display_stylesheet() -> str:
    """Stylesheet for the ChatDisplay widget. Must include background-color
    so Qt doesn't fall back to a transparent/default background when the
    palette changes — once setStyleSheet has been called on a widget, the
    QPalette Base role is no longer used for the background."""
    p = palette()
    return f"padding: {SPACING_S}px; background-color: {p.base_bg};"


def pill_stylesheet() -> str:
    """Stylesheet for pending-station pill buttons. Same WCAG goals as the
    chat-display pill spans: ≥4.5:1 text-to-background, distinguishable
    border for non-color cues. F-007: hover state brightens background so
    the button affordance is visible without click-to-test."""
    p = palette()
    return (
        "QPushButton {"
        f" background-color: {p.pill_bg};"
        f" color: {p.pill_text};"
        f" border: 2px solid {p.pill_border};"
        f" padding: {SPACING_XS}px {SPACING_S + SPACING_XS}px;"
        " border-radius: 4px;"
        "}"
        "QPushButton:hover {"
        f" background-color: {p.pill_hover_bg};"
        "}"
        "QPushButton:focus {"
        f" border-color: {p.focus_ring};"
        "}"
    )


def dock_title_stylesheet() -> str:
    """Stylesheet for the CompactTitleBar used by every QDockWidget. Keeps
    the bar visually quiet but distinct from the dock content; the focus
    rule is the keyboard a11y cue that operator-facing audit F-014 calls
    out."""
    p = palette()
    return (
        "QWidget#dockTitleBar {"
        f" background-color: {p.dock_title_bg};"
        f" color: {p.dock_title_text};"
        " border-top-left-radius: 3px;"
        " border-top-right-radius: 3px;"
        "}"
        f"QWidget#dockTitleBar:focus {{ border: 2px solid {p.focus_ring}; }}"
        "QToolButton {"
        " background: transparent; border: none;"
        f" color: {p.dock_title_text};"
        " padding: 1px 4px;"
        "}"
        "QToolButton:hover {"
        f" background-color: {p.header_border};"
        " border-radius: 3px;"
        "}"
    )


def toolbar_focus_stylesheet() -> str:
    """Focus-ring stylesheet for the service toolbar's QToolButton row.
    Audit F-014: ``autoRaise=True`` tool buttons have no painted resting
    state, so Qt's default focus rect is often invisible. An explicit
    border picks them out for keyboard-only operators."""
    p = palette()
    return (
        "QToolButton:focus {"
        f" border: 2px solid {p.focus_ring};"
        " border-radius: 3px;"
        "}"
    )
