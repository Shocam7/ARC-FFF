import logging
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

logger = logging.getLogger(__name__)

class StatusPill(QWidget):
    """
    A floating, pill-shaped status indicator for the Computer Use agent.
    Positioned in the corner to avoid hindering main UI.
    """
    def __init__(self):
        super().__init__()
        # Frameless, stays on top, tool window (hidden from taskbar)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Main layout
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # The pill background
        self.pill = QFrame()
        self.pill.setStyleSheet("""
            QFrame {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, 
                                                  stop:0 rgba(30, 30, 35, 240), 
                                                  stop:1 rgba(20, 20, 25, 240));
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 10);
            }
        """)
        
        self.pill_layout = QHBoxLayout(self.pill)
        self.pill_layout.setContentsMargins(16, 8, 16, 8)
        self.pill_layout.setSpacing(12)
        
        # Status text
        self.label = QLabel("Computer Use Idle")
        self.label.setStyleSheet("color: #e8eaed; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; font-weight: 500;")
        
        # Red square indicator (like a recording icon)
        self.indicator = QFrame()
        self.indicator.setFixedSize(12, 12)
        self.indicator.setStyleSheet("background-color: #ea4335; border-radius: 2px;")
        
        self.pill_layout.addWidget(self.label)
        self.pill_layout.addWidget(self.indicator)
        
        self.main_layout.addWidget(self.pill)
        
        self.adjustSize()
        self.anchor_to_corner()
        
        # Timer to hide after completion
        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def anchor_to_corner(self):
        """Position the pill in the top-right corner."""
        screen = self.screen().availableGeometry()
        self.adjustSize()
        # 20px margin from top and right
        x = screen.right() - self.width() - 40
        y = screen.top() + 40
        self.move(x, y)

    def update_status(self, text: str, status: str = "running"):
        """Update the pill text and visibility based on status."""
        self.label.setText(text)
        
        if status == "running":
            self.indicator.setStyleSheet("background-color: #ea4335; border-radius: 2px;") # Red active
            self.show()
            self.raise_()
            self._hide_timer.stop()
        elif status == "awaiting":
            self.indicator.setStyleSheet("background-color: #4285f4; border-radius: 2px;") # Blue waiting
            self.show()
            self.raise_()
            self._hide_timer.stop()
        elif status == "completed":
            self.indicator.setStyleSheet("background-color: #34a853; border-radius: 2px;") # Green done
            self._hide_timer.start(3000) # Hide after 3 seconds
        elif status == "failed":
            self.indicator.setStyleSheet("background-color: #fbbc04; border-radius: 2px;") # Yellow error
            self._hide_timer.start(5000) # Hide after 5 seconds
        else:
            self.hide()
            
        self.adjustSize()
        self.anchor_to_corner()
