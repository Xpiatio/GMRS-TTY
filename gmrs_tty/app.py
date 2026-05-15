import sys

from PySide6.QtWidgets import QApplication

from gmrs_tty.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    # Apply a clean, default styling
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
