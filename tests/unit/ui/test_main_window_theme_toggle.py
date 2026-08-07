"""Dark-mode toggle on MainWindow.

A 🌙 / ☀️ QToolButton sits on the service toolbar, between the FRS
radio's stretch spacer and the Q quick-messages icon. Clicking it flips
the active palette, persists ``dark_mode`` to config.json, and repaints
every widget that hardcodes colors outside QPalette (header label,
pending-station pills, chat display, online indicator, dock title bars).
On startup the persisted preference is honored so the user lands in the
theme they last selected.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar  # noqa: E402

from gmrs_tty.ui import theme  # noqa: E402


def _service_toolbar_widgets(window):
    """Return the widgets hosted by the service toolbar, left-to-right."""
    toolbar = window.findChild(QToolBar, "toolbar.service")
    if toolbar is None:
        return []
    return [a.defaultWidget() for a in toolbar.actions()]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


def _make_window(qapp, *, dark_mode=None, save_capture=None):
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233", "name": "Ben", "location": "Jenison",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }
    if dark_mode is not None:
        config["dark_mode"] = dark_mode

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    def fake_save_json(path, data):
        if save_capture is not None:
            save_capture.append((path, dict(data) if isinstance(data, dict) else data))

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch("gmrs_tty.config.save_json", side_effect=fake_save_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        return mw_mod.MainWindow()


@pytest.fixture
def reset_theme():
    """Reset palette state back to light after each test. The theme module
    is process-global, so a test that toggles into dark would leak state
    into the next test's fixture if we didn't snap it back."""
    yield
    theme.set_dark(False)
    app = QApplication.instance()
    if app is not None:
        theme.apply_theme(app, False)


class TestThemeToggleButtonExists:
    def test_button_lives_on_service_row(self, qapp, reset_theme):
        # The toggle has to be reachable from the service toolbar so it
        # sits alongside the GMRS/FRS radios and the icon strip — we
        # don't want it buried in a menu where discoverability collapses.
        window = _make_window(qapp)
        try:
            assert window.theme_toggle_btn in _service_toolbar_widgets(window), (
                "theme toggle must be hosted by the service toolbar"
            )
        finally:
            window.close()

    def test_button_is_leftmost_in_icon_strip(self, qapp, reset_theme):
        # Layout intent: [🌙] | [Q] | [👤] | [⚙️]. The theme toggle goes
        # first because it's the only icon that isn't "open a dialog" —
        # grouping the three dialog-launchers on the right keeps the
        # visual rhythm.
        window = _make_window(qapp)
        try:
            widgets = _service_toolbar_widgets(window)
            theme_btn = window.theme_toggle_btn
            q_btn = window.quick_messages_icon_btn
            contacts_btn = window.contacts_icon_btn
            config_btn = window.config_icon_btn
            for btn in (theme_btn, q_btn, contacts_btn, config_btn):
                assert btn in widgets, f"missing {btn.accessibleName()} from toolbar"
            assert (
                widgets.index(theme_btn)
                < widgets.index(q_btn)
                < widgets.index(contacts_btn)
                < widgets.index(config_btn)
            ), "icon order must be theme → Q → contacts → config"
        finally:
            window.close()

    def test_button_has_accessible_label(self, qapp, reset_theme):
        # Icon-only buttons need an accessibleName so screen readers don't
        # fall back to announcing "crescent moon".
        window = _make_window(qapp)
        try:
            name = window.theme_toggle_btn.accessibleName().lower()
            assert "dark" in name or "theme" in name, name
        finally:
            window.close()

    def test_button_stays_enabled_in_frs_mode(self, qapp, reset_theme):
        # The theme is service-agnostic; FRS shouldn't lock the user out.
        window = _make_window(qapp)
        try:
            assert window.theme_toggle_btn.isEnabled() is True
            window.frs_radio.setChecked(True)
            assert window.theme_toggle_btn.isEnabled() is True
        finally:
            window.close()


class TestThemeToggleGlyph:
    def test_light_mode_shows_moon(self, qapp, reset_theme):
        # In light mode the icon advertises the destination — the moon is
        # the "click to go dark" cue.
        window = _make_window(qapp, dark_mode=False)
        try:
            assert "\U0001F319" in window.theme_toggle_btn.text()
        finally:
            window.close()

    def test_dark_mode_shows_sun(self, qapp, reset_theme):
        window = _make_window(qapp, dark_mode=True)
        try:
            assert "☀" in window.theme_toggle_btn.text()
        finally:
            window.close()

    def test_glyph_flips_after_toggle(self, qapp, reset_theme):
        # After clicking the toggle the icon has to update so the next
        # click's destination is correctly advertised.

        window = _make_window(qapp, dark_mode=False)
        try:
            before = window.theme_toggle_btn.text()
            with patch("gmrs_tty.config.save_json"):
                window.theme_toggle_btn.click()
            after = window.theme_toggle_btn.text()
            assert before != after, "toggle did not update its glyph"
        finally:
            window.close()


class TestThemeTogglePersistence:
    def test_click_writes_dark_mode_true_to_config(self, qapp, reset_theme):
        # Persistence: the click path must save through save_json so the
        # next launch lands in the user's chosen theme. The fixture only
        # patches save_json during construction; re-patch here so the
        # click-time call is captured.

        saved = []
        window = _make_window(qapp, dark_mode=False)
        try:
            def capture(path, data):
                saved.append((path, dict(data) if isinstance(data, dict) else data))

            with patch("gmrs_tty.config.save_json", side_effect=capture):
                window.theme_toggle_btn.click()
            payloads = [data for _, data in saved if isinstance(data, dict)]
            assert payloads, "expected save_json to be called with the config dict"
            assert payloads[-1].get("dark_mode") is True
            assert window.config.get("dark_mode") is True
        finally:
            window.close()

    def test_second_click_flips_back_to_light(self, qapp, reset_theme):

        saved = []
        window = _make_window(qapp, dark_mode=False)
        try:
            def capture(path, data):
                saved.append((path, dict(data) if isinstance(data, dict) else data))

            with patch("gmrs_tty.config.save_json", side_effect=capture):
                window.theme_toggle_btn.click()
                window.theme_toggle_btn.click()
            payloads = [data for _, data in saved if isinstance(data, dict)]
            assert payloads[-1].get("dark_mode") is False
            assert window.config.get("dark_mode") is False
        finally:
            window.close()


class TestThemeStartupApplication:
    def test_startup_with_dark_mode_true_activates_dark_palette(self, qapp, reset_theme):
        # Honoring the persisted preference at startup is the entire point
        # of saving it — verify the palette is active before any user
        # interaction.
        window = _make_window(qapp, dark_mode=True)
        try:
            assert theme.is_dark() is True
            assert theme.palette() is theme.DARK
        finally:
            window.close()

    def test_startup_with_dark_mode_missing_defaults_to_light(self, qapp, reset_theme):
        # First-run users have no dark_mode key — they should land in the
        # documented default (light).
        window = _make_window(qapp)
        try:
            assert theme.is_dark() is False
            assert theme.palette() is theme.LIGHT
        finally:
            window.close()


class TestThemeAppliedToWidgets:
    def test_header_stylesheet_reflects_active_palette(self, qapp, reset_theme):
        # The header label uses an inline stylesheet (it's not a QPalette
        # role), so the toggle path has to update it explicitly. Patch
        # save_json again so the click doesn't hit the real config file.

        window = _make_window(qapp, dark_mode=False)
        try:
            light_sheet = window.header_label.styleSheet()
            assert theme.LIGHT.header_bg.lower() in light_sheet.lower()
            with patch("gmrs_tty.config.save_json"):
                window.theme_toggle_btn.click()
            dark_sheet = window.header_label.styleSheet()
            assert theme.DARK.header_bg.lower() in dark_sheet.lower()
            assert light_sheet != dark_sheet
        finally:
            window.close()

    def test_pending_pills_restyle_on_toggle(self, qapp, reset_theme):
        # Live pending pills mustn't keep their light-mode amber-100 bg
        # against a dark window — the toggle path must walk
        # pending_buttons and reapply the current pill stylesheet.

        window = _make_window(qapp, dark_mode=False)
        try:
            window.pending_manager.add_pending_station("WSLZ999", "Test", "Nowhere")
            btn = window.pending_manager.buttons["WSLZ999"]
            assert theme.LIGHT.pill_bg.lower() in btn.styleSheet().lower()
            with patch("gmrs_tty.config.save_json"):
                window.theme_toggle_btn.click()
            assert theme.DARK.pill_bg.lower() in btn.styleSheet().lower()
        finally:
            window.close()
