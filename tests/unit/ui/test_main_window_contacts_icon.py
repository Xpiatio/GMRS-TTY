"""Quick-access icons on the service toolbar.

Three icon buttons sit at the right edge of the service toolbar,
left-to-right: a bold "Q" that opens Quick Messages, a person-head icon
that opens Contacts, and a cog wheel that opens Configuration. They are
discoverability affordances — operators shouldn't have to learn the menu
paths to reach these dialogs. Phase B moved the service row from a
QHBoxLayout into a movable QToolBar, so structural assertions now walk
the toolbar's widget chain rather than a nested-layout tree."""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar  # noqa: E402


def _service_toolbar_widgets(window):
    """Return the ordered list of widgets hosted by the service toolbar.

    QToolBar wraps every addWidget() call in a QAction whose
    defaultWidget() points back at the widget; iterating actions in
    insertion order recovers the visual left-to-right sequence.
    """
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


@pytest.fixture
def main_window(qapp):
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233", "name": "Ben", "location": "Jenison",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "save_json"), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        window = mw_mod.MainWindow()
    yield window
    window.close()


class TestContactsIconButton:
    def test_button_exists_on_service_row(self, main_window):
        # The icon must live on the service toolbar so it sits on the top
        # bar alongside the GMRS / FRS radios.
        btn = main_window.contacts_icon_btn
        assert btn in _service_toolbar_widgets(main_window), (
            "contacts icon must be hosted by the service toolbar"
        )

    def test_button_text_is_a_person_glyph(self, main_window):
        # The button is icon-only — the glyph IS the affordance. If the
        # text drifts away from a person/head character (cleanup refactor,
        # font fallback edit) the button stops looking like contacts.
        assert main_window.contacts_icon_btn.text() == "\U0001F464"

    def test_button_has_accessible_label(self, main_window):
        # Icon-only buttons are an accessibility hazard without an
        # accessible name. Screen readers fall back to the (emoji) text
        # otherwise, which announces as "bust in silhouette".
        name = main_window.contacts_icon_btn.accessibleName().lower()
        assert "contact" in name, name

    def test_click_opens_contacts_dialog(self, main_window):
        # Wiring check: the button calls the same code path as the menu
        # action so any future change to open_contacts_dialog (e.g. extra
        # confirmation, FRS guard tightened) automatically applies here.
        with patch.object(main_window, "open_contacts_dialog") as opener:
            main_window.contacts_icon_btn.click()
        opener.assert_called_once()


class TestConfigIconButton:
    def test_button_exists_on_service_row(self, main_window):
        btn = main_window.config_icon_btn
        assert btn in _service_toolbar_widgets(main_window), (
            "config cog must be hosted by the service toolbar"
        )

    def test_cog_is_rightmost_in_service_row(self, main_window):
        # The "settings is last" convention on toolbars is well-established;
        # the cog must sit to the right of the contacts icon (not the other
        # way around) so it's where operators expect to find it.
        widgets = _service_toolbar_widgets(main_window)
        assert main_window.contacts_icon_btn in widgets
        assert main_window.config_icon_btn in widgets
        assert widgets.index(main_window.contacts_icon_btn) < widgets.index(
            main_window.config_icon_btn
        ), "config cog should be rightmost on the toolbar"

    def test_button_text_is_a_gear_glyph(self, main_window):
        # U+2699 is the canonical gear/cog codepoint. If the text drifts the
        # button stops looking like settings.
        assert "⚙" in main_window.config_icon_btn.text()

    def test_button_has_accessible_label(self, main_window):
        name = main_window.config_icon_btn.accessibleName().lower()
        assert "config" in name, name

    def test_click_opens_config_dialog(self, main_window):
        with patch.object(main_window, "open_config_dialog") as opener:
            main_window.config_icon_btn.click()
        opener.assert_called_once()

    def test_config_icon_stays_enabled_in_frs_mode(self, main_window):
        # Configuration is service-agnostic (voice, audio devices, PTT) —
        # it must remain reachable from FRS mode where the contacts icon
        # disables alongside the rest of the callsign-specific UI.
        assert main_window.config_icon_btn.isEnabled() is True
        main_window.frs_radio.setChecked(True)
        assert main_window.config_icon_btn.isEnabled() is True


class TestQuickMessagesIconButton:
    def test_button_exists_on_service_row(self, main_window):
        btn = main_window.quick_messages_icon_btn
        assert btn in _service_toolbar_widgets(main_window), (
            "Q icon must be hosted by the service toolbar"
        )

    def test_button_text_is_q(self, main_window):
        # The letter Q is the affordance — the button has no other label.
        assert main_window.quick_messages_icon_btn.text() == "Q"

    def test_button_has_accessible_label(self, main_window):
        name = main_window.quick_messages_icon_btn.accessibleName().lower()
        assert "quick" in name and "message" in name, name

    def test_click_opens_quick_messages_dialog(self, main_window):
        with patch.object(main_window, "open_quick_messages_dialog") as opener:
            main_window.quick_messages_icon_btn.click()
        opener.assert_called_once()

    def test_quick_messages_icon_stays_enabled_in_frs_mode(self, main_window):
        # Quick Messages drive plain-text TX which is just as valid in FRS
        # (presets transmit through the same pipeline, minus the callsign
        # preface). The icon must stay reachable in both modes.
        assert main_window.quick_messages_icon_btn.isEnabled() is True
        main_window.frs_radio.setChecked(True)
        assert main_window.quick_messages_icon_btn.isEnabled() is True

    def test_icon_trio_order_q_then_contacts_then_config(self, main_window):
        """Left-to-right ordering on the service toolbar: Q | 👤 | ⚙️.
        Q sits leftmost (closest to the chat surface it feeds), Contacts
        in the middle, Configuration rightmost ("settings last")."""
        widgets = _service_toolbar_widgets(main_window)
        q_btn = main_window.quick_messages_icon_btn
        contacts_btn = main_window.contacts_icon_btn
        config_btn = main_window.config_icon_btn
        for btn in (q_btn, contacts_btn, config_btn):
            assert btn in widgets, f"missing {btn.accessibleName()} from toolbar"
        assert (
            widgets.index(q_btn)
            < widgets.index(contacts_btn)
            < widgets.index(config_btn)
        ), "icon order must be Q → contacts → config"
