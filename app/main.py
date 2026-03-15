"""
main.py
───────
ARC — AI Panel Conference  (renamed from arc.py)

Run with:
    cd app
    uv run --project .. python main.py
"""

import sys
import warnings

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore    import Qt

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("ARC")
    app.setOrganizationName("ARC")

    from arc.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()