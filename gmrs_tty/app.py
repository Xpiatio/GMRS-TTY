import sys
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gmrs_tty.ui.main_window import MainWindow

_RESOURCES = Path(__file__).parent / "resources"
_ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]


def _build_icon() -> QIcon:
    icon = QIcon()
    for sz in _ICON_SIZES:
        path = _RESOURCES / f"icon_{sz}.png"
        if path.exists():
            icon.addFile(str(path), QSize(sz, sz))
    return icon


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(_build_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
