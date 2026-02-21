"""
PrimeBooks Desktop - First Time Setup Window
Drop this class into main.py and use SetupProgressWindow instead of QProgressDialog
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QFrame
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, pyqtProperty, QObject
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QLinearGradient, QRadialGradient, QPainterPath
import math


class PulsingDot(QWidget):
    """Animated pulsing dot indicator"""

    def __init__(self, color="#4ade80", parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.pulse = 0.0
        self.setFixedSize(12, 12)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(30)
        self._step = 0

    def _animate(self):
        self._step += 1
        self.pulse = (math.sin(self._step * 0.1) + 1) / 2
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer glow
        glow_color = QColor(self.color)
        glow_color.setAlpha(int(60 * self.pulse))
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 12, 12)

        # Inner dot
        inner_color = QColor(self.color)
        inner_color.setAlpha(200 + int(55 * self.pulse))
        painter.setBrush(QBrush(inner_color))
        offset = int(2 * (1 - self.pulse * 0.3))
        size = 12 - offset * 2
        painter.drawEllipse(offset, offset, size, size)


class SpinnerWidget(QWidget):
    """Clean circular spinner"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.start(16)

    def _rotate(self):
        self._angle = (self._angle + 4) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy, r = 24, 24, 18

        # Track circle
        track_pen = QPen(QColor(255, 255, 255, 25))
        track_pen.setWidth(3)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Spinning arc — gradient from bright to transparent
        for i in range(120):
            angle = self._angle - i
            alpha = int(255 * (1 - i / 120) ** 1.5)
            if alpha < 5:
                continue
            color = QColor(74, 222, 128, alpha)
            arc_pen = QPen(color)
            arc_pen.setWidth(3)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            rad = math.radians(angle)
            x1 = cx + r * math.cos(rad)
            y1 = cy + r * math.sin(rad)
            rad2 = math.radians(angle - 3)
            x2 = cx + r * math.cos(rad2)
            y2 = cy + r * math.sin(rad2)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))


class SetupProgressWindow(QDialog):
    """
    Beautiful first-time setup window.

    Usage:
        win = SetupProgressWindow()
        win.show()
        # ... run migrations ...
        win.set_message("Almost done...")
        # ... finish ...
        win.close()
    """

    MESSAGES = [
        ("Initializing database engine...", "Building the foundation"),
        ("Creating schema tables...", "Setting up your workspace"),
        ("Running migrations...", "This takes about 30-60 seconds"),
        ("Configuring relationships...", "Linking everything together"),
        ("Applying security settings...", "Keeping your data safe"),
        ("Preparing your workspace...", "Almost there"),
        ("Finalizing setup...", "Just a moment more"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PrimeBooks")
        self.setModal(True)
        self.setFixedSize(520, 420)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._msg_index = 0
        self._dots = 0

        self._build_ui()
        self._start_rotation()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Main card
        self.card = QFrame(self)
        self.card.setFixedSize(520, 420)
        self.card.setStyleSheet("""
            QFrame {
                background-color: #0f1117;
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.08);
            }
        """)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(0)

        # ── Top bar ────────────────────────────────────────────────────────
        top_bar = QHBoxLayout()

        app_label = QLabel("PRIMEBOOKS")
        app_label.setStyleSheet("""
            color: rgba(255,255,255,0.35);
            font-family: 'Courier New', monospace;
            font-size: 11px;
            letter-spacing: 4px;
            font-weight: bold;
        """)
        top_bar.addWidget(app_label)
        top_bar.addStretch()

        self.dot = PulsingDot("#4ade80")
        top_bar.addWidget(self.dot)

        status_label = QLabel("SETTING UP")
        status_label.setStyleSheet("""
            color: #4ade80;
            font-family: 'Courier New', monospace;
            font-size: 10px;
            letter-spacing: 3px;
            margin-left: 6px;
        """)
        top_bar.addWidget(status_label)

        layout.addLayout(top_bar)
        layout.addSpacing(40)

        # ── Spinner + heading ──────────────────────────────────────────────
        center_row = QHBoxLayout()
        center_row.setSpacing(24)

        self.spinner = SpinnerWidget()
        center_row.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        self.heading = QLabel("First Time Setup")
        self.heading.setStyleSheet("""
            color: #ffffff;
            font-size: 26px;
            font-weight: 700;
            font-family: Georgia, 'Times New Roman', serif;
            letter-spacing: -0.5px;
        """)
        text_col.addWidget(self.heading)

        self.sub = QLabel("Preparing your accounting workspace")
        self.sub.setStyleSheet("""
            color: rgba(255,255,255,0.45);
            font-size: 13px;
            font-family: 'Trebuchet MS', sans-serif;
        """)
        text_col.addWidget(self.sub)
        center_row.addLayout(text_col)
        center_row.addStretch()

        layout.addLayout(center_row)
        layout.addSpacing(40)

        # ── Divider ────────────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background: rgba(255,255,255,0.07); max-height: 1px; border: none;")
        layout.addWidget(divider)
        layout.addSpacing(28)

        # ── Current step message ───────────────────────────────────────────
        self.step_label = QLabel("Initializing database engine...")
        self.step_label.setStyleSheet("""
            color: rgba(255,255,255,0.85);
            font-size: 14px;
            font-family: 'Trebuchet MS', sans-serif;
            font-weight: 500;
        """)
        layout.addWidget(self.step_label)
        layout.addSpacing(6)

        self.step_sub = QLabel("Building the foundation")
        self.step_sub.setStyleSheet("""
            color: rgba(255,255,255,0.30);
            font-size: 12px;
            font-family: 'Trebuchet MS', sans-serif;
        """)
        layout.addWidget(self.step_sub)

        layout.addStretch()

        # ── Bottom note ────────────────────────────────────────────────────
        note = QLabel("This only happens once. Future starts are instant.")
        note.setStyleSheet("""
            color: rgba(255,255,255,0.20);
            font-size: 11px;
            font-family: 'Trebuchet MS', sans-serif;
            font-style: italic;
        """)
        layout.addWidget(note, 0, Qt.AlignmentFlag.AlignCenter)

        outer.addWidget(self.card)

    def _start_rotation(self):
        self._msg_timer = QTimer(self)
        self._msg_timer.timeout.connect(self._next_message)
        self._msg_timer.start(5000)

    def _next_message(self):
        self._msg_index = (self._msg_index + 1) % len(self.MESSAGES)
        msg, sub = self.MESSAGES[self._msg_index]
        self.step_label.setText(msg)
        self.step_sub.setText(sub)

    def set_message(self, message, sub=""):
        """Manually set the current message"""
        self.step_label.setText(message)
        self.step_sub.setText(sub)

    def paintEvent(self, event):
        """Draw subtle outer shadow"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(8):
            shadow = QColor(0, 0, 0, 15 - i)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(shadow))
            painter.drawRoundedRect(
                i, i, self.width() - i * 2, self.height() - i * 2, 22, 22
            )

    def closeEvent(self, event):
        if hasattr(self, '_msg_timer'):
            self._msg_timer.stop()
        self.spinner._timer.stop()
        self.dot._timer.stop()
        super().closeEvent(event)