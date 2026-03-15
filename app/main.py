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
from dotenv import load_dotenv
load_dotenv()

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("ARC")
    app.setOrganizationName("ARC")

    from arc.web.livekit_bridge import LiveKitBridge
    lk_bridge = LiveKitBridge()
    lk_bridge.start_background()

    from arc.ui.main_window import MainWindow
    win = MainWindow(lk_bridge=lk_bridge)
    win.show()
    
    code = app.exec()
    sys.exit(code)


if __name__ == "__main__":
    main()