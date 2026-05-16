import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidgetItem  # noqa: E402

from gmrs_tty.ui.quick_messages_dialog import QuickMessagesDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _set_cell(dlg, row, text):
    dlg.table.setItem(row, 0, QTableWidgetItem(text))


class TestRoundTrip:
    def test_initial_list_round_trips_unchanged(self, qapp):
        seed = ["Radio check", "Standing by", "QSY to channel {N}"]
        dlg = QuickMessagesDialog(seed)
        assert dlg.get_quick_messages() == seed

    def test_empty_seed_returns_empty_list(self, qapp):
        dlg = QuickMessagesDialog([])
        assert dlg.get_quick_messages() == []

    def test_blank_rows_are_dropped_on_save(self, qapp):
        # Hand-editing might leave an empty row; the strip should never show
        # an unlabeled button so the dialog filters blanks on the way out.
        dlg = QuickMessagesDialog(["Radio check"])
        dlg._add_row()
        _set_cell(dlg, 1, "   ")
        dlg._add_row()
        _set_cell(dlg, 2, "Standing by")
        assert dlg.get_quick_messages() == ["Radio check", "Standing by"]


class TestEditing:
    def test_add_row_creates_blank_entry(self, qapp):
        dlg = QuickMessagesDialog(["Radio check"])
        assert dlg.table.rowCount() == 1
        dlg._add_row()
        assert dlg.table.rowCount() == 2

    def test_remove_row_deletes_current(self, qapp):
        dlg = QuickMessagesDialog(["Radio check", "Standing by", "Clear"])
        dlg.table.setCurrentCell(1, 0)
        dlg._remove_row()
        assert dlg.get_quick_messages() == ["Radio check", "Clear"]

    def test_remove_with_no_selection_is_noop(self, qapp):
        dlg = QuickMessagesDialog(["Radio check"])
        dlg.table.setCurrentCell(-1, -1)
        dlg._remove_row()
        assert dlg.get_quick_messages() == ["Radio check"]


class TestReordering:
    def test_move_up_swaps_with_previous_row(self, qapp):
        dlg = QuickMessagesDialog(["A", "B", "C"])
        dlg.table.setCurrentCell(2, 0)
        dlg._move_row(-1)
        assert dlg.get_quick_messages() == ["A", "C", "B"]

    def test_move_down_swaps_with_next_row(self, qapp):
        dlg = QuickMessagesDialog(["A", "B", "C"])
        dlg.table.setCurrentCell(0, 0)
        dlg._move_row(1)
        assert dlg.get_quick_messages() == ["B", "A", "C"]

    def test_move_up_at_top_is_noop(self, qapp):
        dlg = QuickMessagesDialog(["A", "B"])
        dlg.table.setCurrentCell(0, 0)
        dlg._move_row(-1)
        assert dlg.get_quick_messages() == ["A", "B"]

    def test_move_down_at_bottom_is_noop(self, qapp):
        dlg = QuickMessagesDialog(["A", "B"])
        dlg.table.setCurrentCell(1, 0)
        dlg._move_row(1)
        assert dlg.get_quick_messages() == ["A", "B"]

    def test_move_keeps_selection_with_moved_row(self, qapp):
        # The selection should follow the row the operator just nudged so
        # repeated Move Up clicks keep moving the same phrase.
        dlg = QuickMessagesDialog(["A", "B", "C"])
        dlg.table.setCurrentCell(2, 0)
        dlg._move_row(-1)
        assert dlg.table.currentRow() == 1
