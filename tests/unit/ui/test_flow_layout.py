import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from gmrs_tty.ui.flow_layout import FlowLayout  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _populate(layout, n, label="+ Add WSLZ123"):
    for _ in range(n):
        layout.addWidget(QPushButton(label))


class TestFlowLayout:
    def test_count_tracks_added_items(self, qapp):
        w = QWidget()
        layout = FlowLayout(w, spacing=5)
        _populate(layout, 4)
        assert layout.count() == 4

    def test_take_at_removes_item(self, qapp):
        w = QWidget()
        layout = FlowLayout(w, spacing=5)
        _populate(layout, 3)
        layout.takeAt(0)
        assert layout.count() == 2

    def test_narrower_width_yields_more_height(self, qapp):
        """The whole point of flow: less width → more wrapped rows → taller."""
        w = QWidget()
        layout = FlowLayout(w, spacing=5)
        _populate(layout, 8)
        narrow = layout.heightForWidth(200)
        wide = layout.heightForWidth(4000)
        assert narrow > wide

    def test_single_item_fits_one_row(self, qapp):
        w = QWidget()
        layout = FlowLayout(w, spacing=5)
        _populate(layout, 1)
        item = layout.itemAt(0)
        assert layout.heightForWidth(1000) <= item.sizeHint().height() + 1

    def test_reports_height_for_width(self, qapp):
        w = QWidget()
        layout = FlowLayout(w, spacing=5)
        assert layout.hasHeightForWidth() is True
