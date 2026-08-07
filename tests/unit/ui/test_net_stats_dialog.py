"""NetStatsDialog — session list, detail rendering, stats grid, delete guard."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import gmrs_tty.ui.net_stats_dialog as dlg_mod  # noqa: E402
from gmrs_tty.ui.net_stats_dialog import NetStatsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    """Point the dialog's persistence helpers at a temp sessions dir."""
    from gmrs_tty.persistence import net_sessions

    monkeypatch.setattr(
        dlg_mod, "load_session_summaries",
        lambda: net_sessions.load_session_summaries(tmp_path),
    )
    monkeypatch.setattr(
        dlg_mod, "load_session",
        lambda sid: net_sessions.load_session(sid, tmp_path),
    )
    monkeypatch.setattr(
        dlg_mod, "delete_session",
        lambda sid: net_sessions.delete_session(sid, tmp_path),
    )
    return tmp_path


def _write_session(sessions_dir, session_id, stations):
    (sessions_dir / f"{session_id}.json").write_text(json.dumps({
        "id": session_id,
        "started_at": "2026-08-07T12:00:00+00:00",
        "ended_at": "2026-08-07T12:30:00+00:00",
        "duration_seconds": 1800,
        "roster": [
            {"callsign": cs, "name": name, "location": "", "gmrs": "", "ham": ""}
            for cs, name in stations
        ],
    }))


class TestEmptyState:
    def test_placeholder_shown(self, qapp, sessions_dir):
        dlg = NetStatsDialog()
        assert dlg._list.count() == 1
        assert "No sessions" in dlg._list.item(0).text()
        assert not dlg._export_all_btn.isEnabled()
        assert not dlg._export_stats_btn.isEnabled()


class TestPopulated:
    def test_sessions_listed_and_detail_rendered(self, qapp, sessions_dir):
        _write_session(sessions_dir, "20260807_120000", [("WSLZ233", "Ben")])
        dlg = NetStatsDialog()
        assert dlg._list.count() == 1
        assert "1 station(s)" in dlg._list.item(0).text()
        assert "WSLZ233" in dlg._detail.toPlainText()
        assert dlg._export_btn.isEnabled()
        assert dlg._export_all_btn.isEnabled()

    def test_stats_grid_populated(self, qapp, sessions_dir):
        _write_session(sessions_dir, "20260807_120000", [("WSLZ233", "Ben")])
        _write_session(sessions_dir, "20260801_120000", [("WSLZ233", "Ben")])
        dlg = NetStatsDialog()
        assert dlg._stats_table.rowCount() == 1
        assert dlg._stats_table.item(0, 0).text() == "WSLZ233"
        assert dlg._stats_table.item(0, 2).text() == "2"  # total nets
        assert dlg._export_stats_btn.isEnabled()

    def test_shared_callsign_distinct_names_get_own_rows(self, qapp, sessions_dir):
        _write_session(
            sessions_dir, "20260807_120000",
            [("WSLZ233", "Ben"), ("WSLZ233", "Alex")],
        )
        dlg = NetStatsDialog()
        assert dlg._stats_table.rowCount() == 2


class TestAccessibility:
    def test_interactive_widgets_have_accessible_names(self, qapp, sessions_dir):
        dlg = NetStatsDialog()
        for widget in (
            dlg._list, dlg._detail, dlg._stats_table, dlg._delete_btn,
            dlg._export_btn, dlg._export_all_btn, dlg._export_stats_btn,
        ):
            assert widget.accessibleName(), widget
