import signal
import sys
from pathlib import Path

from PySide6.QtCore import QSize, QTimer
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

    # Forward Ctrl+C to Qt's quit slot so closeEvent runs and all worker
    # threads are torn down cleanly before the process exits.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # QTimer wakes Python's signal-checker between Qt events so the handler
    # above is called promptly even when the event loop is otherwise idle.
    _sigcheck = QTimer()
    _sigcheck.start(200)
    _sigcheck.timeout.connect(lambda: None)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
