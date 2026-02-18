"""
Sync Progress Dialog — Refined Dark Theme
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Transient toast on sync start → auto-hides
✅ Full result dialog on success / error only
✅ Dismissable at any time (focus-loss aware)
✅ Consistent dark palette with slate/zinc tones
✅ Monospaced activity log with color tokens
✅ Per-model mini-progress with live stats
✅ Pause / Resume / Cancel controls
"""

import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTextEdit, QScrollArea, QWidget, QFrame,
    QSizePolicy, QMessageBox, QGraphicsOpacityEffect
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QPoint, QRect, QSize, QThread
)
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QLinearGradient
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Palette
# ──────────────────────────────────────────────
_P = {
    "bg":           "#0f1117",   # deepest background
    "surface":      "#161b22",   # card surface
    "surface2":     "#1c2230",   # elevated surface
    "border":       "#21262d",   # subtle border
    "border2":      "#30363d",   # stronger border
    "text":         "#e6edf3",   # primary text
    "text2":        "#8b949e",   # secondary text
    "text3":        "#484f58",   # muted / disabled
    "accent":       "#388bfd",   # blue accent
    "accent2":      "#58a6ff",   # lighter blue
    "green":        "#3fb950",
    "green2":       "#26a641",
    "yellow":       "#d29922",
    "red":          "#f85149",
    "red2":         "#da3633",
    "purple":       "#bc8cff",
    "teal":         "#39d353",
}

# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────
class SyncTheme(Enum):
    DARK = "dark"

class SyncStatus(Enum):
    IDLE      = "idle"
    RUNNING   = "running"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


# ──────────────────────────────────────────────
# Shared Stylesheet
# ──────────────────────────────────────────────
GLOBAL_STYLE = f"""
    * {{
        font-family: 'SF Mono', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 12px;
        color: {_P['text']};
        outline: none;
    }}

    QDialog, QWidget {{
        background-color: {_P['bg']};
    }}

    QScrollArea {{
        border: none;
        background-color: transparent;
    }}

    QScrollBar:vertical {{
        background: {_P['surface']};
        width: 6px;
        border-radius: 3px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {_P['border2']};
        border-radius: 3px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {_P['text3']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar:horizontal {{
        height: 0;
    }}

    /* ── Cards ── */
    .card {{
        background-color: {_P['surface']};
        border: 1px solid {_P['border']};
        border-radius: 8px;
    }}

    /* ── Labels ── */
    QLabel#heading {{
        font-size: 18px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: {_P['text']};
    }}
    QLabel#subheading {{
        font-size: 12px;
        color: {_P['text2']};
    }}
    QLabel#sectionTitle {{
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.8px;
        color: {_P['text2']};
        text-transform: uppercase;
    }}

    /* ── Progress Bars ── */
    QProgressBar#mainBar {{
        border: 1px solid {_P['border2']};
        border-radius: 4px;
        background-color: {_P['surface2']};
        text-align: center;
        font-size: 11px;
        font-weight: 600;
        color: {_P['text2']};
        min-height: 24px;
    }}
    QProgressBar#mainBar::chunk {{
        background-color: {_P['accent']};
        border-radius: 3px;
    }}

    QProgressBar#miniBar {{
        border: none;
        border-radius: 2px;
        background-color: {_P['border2']};
        min-height: 4px;
        max-height: 4px;
        text-align: center;
    }}
    QProgressBar#miniBar::chunk {{
        background-color: {_P['accent']};
        border-radius: 2px;
    }}
    QProgressBar#miniBar[status="completed"]::chunk {{
        background-color: {_P['green']};
    }}
    QProgressBar#miniBar[status="error"]::chunk {{
        background-color: {_P['red']};
    }}

    /* ── Buttons ── */
    QPushButton {{
        border: 1px solid {_P['border2']};
        border-radius: 6px;
        padding: 6px 16px;
        font-size: 12px;
        font-weight: 600;
        background-color: {_P['surface2']};
        color: {_P['text']};
    }}
    QPushButton:hover {{
        background-color: {_P['border2']};
        border-color: {_P['text3']};
    }}
    QPushButton:pressed {{
        background-color: {_P['border']};
    }}
    QPushButton#btnPrimary {{
        background-color: {_P['accent']};
        border-color: {_P['accent']};
        color: white;
    }}
    QPushButton#btnPrimary:hover {{
        background-color: {_P['accent2']};
    }}
    QPushButton#btnDanger {{
        background-color: transparent;
        border-color: {_P['red2']};
        color: {_P['red']};
    }}
    QPushButton#btnDanger:hover {{
        background-color: {_P['red2']};
        color: white;
    }}
    QPushButton#btnWarn {{
        background-color: transparent;
        border-color: {_P['yellow']};
        color: {_P['yellow']};
    }}
    QPushButton#btnWarn:hover {{
        background-color: {_P['yellow']};
        color: {_P['bg']};
    }}
    QPushButton#btnGhost {{
        background-color: transparent;
        border-color: transparent;
        color: {_P['text2']};
        font-size: 11px;
    }}
    QPushButton#btnGhost:hover {{
        color: {_P['text']};
        border-color: {_P['border2']};
    }}

    /* ── Log Text ── */
    QTextEdit#logView {{
        background-color: {_P['bg']};
        border: 1px solid {_P['border']};
        border-radius: 6px;
        padding: 8px;
        font-family: 'SF Mono', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 11px;
        color: {_P['text']};
        selection-background-color: {_P['accent']};
    }}

    /* ── Divider ── */
    QFrame#divider {{
        background-color: {_P['border']};
        max-height: 1px;
        min-height: 1px;
    }}
"""


# ──────────────────────────────────────────────
# Helper: divider
# ──────────────────────────────────────────────
def _divider():
    d = QFrame()
    d.setObjectName("divider")
    d.setFrameShape(QFrame.Shape.HLine)
    return d


# ──────────────────────────────────────────────
# Stat Card
# ──────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, label: str, value: str = "0", accent: str = _P["text2"]):
        super().__init__()
        self.setProperty("class", "card")
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {_P['surface']};
                border: 1px solid {_P['border']};
                border-radius: 8px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)

        self._val = QLabel(value)
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._val.setStyleSheet(
            f"font-size: 26px; font-weight: 700; color: {accent}; border: none;"
        )
        lay.addWidget(self._val)

        lbl = QLabel(label.upper())
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setObjectName("sectionTitle")
        lbl.setStyleSheet(f"color: {_P['text3']}; border: none;")
        lay.addWidget(lbl)

    def set_value(self, v):
        self._val.setText(str(v))


# ──────────────────────────────────────────────
# Model Row
# ──────────────────────────────────────────────
class ModelRow(QWidget):
    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name
        self.setFixedHeight(38)
        self.setStyleSheet("background: transparent;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        # Dot indicator
        self._dot = QLabel("○")
        self._dot.setFixedWidth(14)
        self._dot.setStyleSheet(f"color: {_P['text3']}; font-size: 14px; border: none;")
        lay.addWidget(self._dot)

        # Name
        name = QLabel(model_name)
        name.setStyleSheet(f"color: {_P['text2']}; font-size: 11px; border: none;")
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(name)

        # Mini bar
        self._bar = QProgressBar()
        self._bar.setObjectName("miniBar")
        self._bar.setMaximum(100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(80)
        self._bar.setFixedHeight(4)
        lay.addWidget(self._bar)

        # Stats label
        self._stats = QLabel("—")
        self._stats.setFixedWidth(120)
        self._stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._stats.setStyleSheet(
            f"color: {_P['text3']}; font-size: 10px; border: none;"
        )
        lay.addWidget(self._stats)

    def set_running(self):
        self._dot.setText("●")
        self._dot.setStyleSheet(f"color: {_P['accent2']}; font-size: 14px; border: none;")
        self._stats.setStyleSheet(f"color: {_P['text2']}; font-size: 10px; border: none;")

    def update_progress(self, created: int, updated: int, total: int):
        self.set_running()
        processed = created + updated
        pct = int((processed / total) * 100) if total else 0
        self._bar.setValue(pct)
        self._stats.setText(f"+{created}  ~{updated}")

    def set_completed(self, created: int, updated: int):
        self._dot.setText("●")
        self._dot.setStyleSheet(f"color: {_P['green']}; font-size: 14px; border: none;")
        self._bar.setValue(100)
        self._bar.setProperty("status", "completed")
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {_P['green']}; border-radius: 2px; }}"
        )
        self._stats.setText(f"+{created}  ~{updated}")
        self._stats.setStyleSheet(f"color: {_P['green']}; font-size: 10px; border: none;")

    def set_error(self, message: str):
        self._dot.setText("●")
        self._dot.setStyleSheet(f"color: {_P['red']}; font-size: 14px; border: none;")
        self._bar.setProperty("status", "error")
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {_P['red']}; border-radius: 2px; }}"
        )
        self._stats.setText("error")
        self._stats.setStyleSheet(f"color: {_P['red']}; font-size: 10px; border: none;")


# ──────────────────────────────────────────────
# Toast — transient start notification
# ──────────────────────────────────────────────
class SyncToast(QDialog):
    """
    Tiny frameless toast.
    kind = 'start'   → blue,  "Sync started / Running in background…"
    kind = 'success' → green, "Sync complete / N created, M updated"
    Auto-hides after `duration_ms` ms. Click to dismiss early.
    """

    CONFIGS = {
        "start": {
            "icon":    "⟳",
            "title":   "Sync started",
            "sub":     "Running in background…",
            "color":   _P["accent2"],
            "border":  _P["border2"],
            "bg":      _P["surface2"],
        },
        "success": {
            "icon":    "✓",
            "title":   "Sync complete",
            "sub":     "",          # filled dynamically
            "color":   _P["green"],
            "border":  _P["green2"],
            "bg":      _P["surface2"],
        },
    }

    def __init__(self, parent=None, kind: str = "start",
                 sub_override: str = "", duration_ms: int = 3200):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(False)

        cfg = self.CONFIGS.get(kind, self.CONFIGS["start"])
        if sub_override:
            cfg = dict(cfg)
            cfg["sub"] = sub_override

        self._build_ui(cfg)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0)

        self._anim_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim_in.setDuration(220)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._timer.start(duration_ms)

    def _build_ui(self, cfg: dict):
        self.setFixedSize(320, 60)
        self.setStyleSheet(GLOBAL_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {cfg['bg']};
                border: 1px solid {cfg['border']};
                border-radius: 10px;
            }}
        """)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        icon = QLabel(cfg["icon"])
        icon.setStyleSheet(
            f"font-size: 18px; color: {cfg['color']}; border: none;"
        )
        lay.addWidget(icon)

        texts = QVBoxLayout()
        texts.setSpacing(1)

        title = QLabel(cfg["title"])
        title.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {_P['text']}; border: none;"
        )
        texts.addWidget(title)

        if cfg["sub"]:
            sub = QLabel(cfg["sub"])
            sub.setStyleSheet(
                f"font-size: 10px; color: {_P['text2']}; border: none;"
            )
            texts.addWidget(sub)

        lay.addLayout(texts)
        lay.addStretch()

        outer.addWidget(card)

    def show_at_bottom_right(self):
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        margin = 18
        x = screen.right() - self.width() - margin
        y = screen.bottom() - self.height() - margin
        self.move(x, y)
        self.show()
        self._anim_in.start()

    def _fade_out(self):
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.close)
        anim.start()

    def mousePressEvent(self, event):
        self._timer.stop()
        self._fade_out()


# ──────────────────────────────────────────────
# Main Sync Dialog
# ──────────────────────────────────────────────
class DetailedSyncDialog(QDialog):
    """
    Full sync progress / result dialog.

    Behaviour
    ─────────
    • When sync starts → show SyncToast, keep this hidden.
    • When sync ends   → show this dialog with result.
    • User can force-open mid-sync by calling .show_mid_sync().
    • Dialog is non-modal; closing/defocusing is always allowed.
    """

    cancel_requested = pyqtSignal()
    pause_requested  = pyqtSignal()
    resume_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.sync_status   = SyncStatus.IDLE
        self.start_time    = None
        self.model_rows    = {}          # {name: ModelRow}
        self.is_paused     = False
        self._toast        = None
        self._mid_sync     = False       # user opened mid-sync
        self._can_show     = False       # gate: only _reveal() unlocks this

        self.setWindowTitle("Sync")
        self.setModal(False)
        self.setMinimumSize(820, 580)
        self.resize(960, 640)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )

        self.setStyleSheet(GLOBAL_STYLE)
        self._build_ui()

        # CRITICAL: stay completely invisible until _reveal() is called.
        # Never call .show() / .exec() on this from outside —
        # it surfaces only on failure/cancel, or via show_mid_sync().
        self.hide()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        # ── Public aliases matching the old API so existing callers don't break ──
        # Buttons  (set in _mk_action_bar, aliased there too — kept here for clarity)
        # self.cancel_btn / self.pause_btn / self.close_btn  → set in _mk_action_bar
        # Widgets
        self.main_progress  = self._main_bar        # old: self.main_progress
        self.status_label   = self._status_label    # old: self.status_label
        self.phase_label    = self._phase_badge     # old: self.phase_label
        self.log_text       = self._log             # old: self.log_text
        self.model_widgets  = self.model_rows       # old: self.model_widgets (dict)

    # ─────────────────────── UI Build ─────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar
        root.addWidget(self._mk_header())

        # ── Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        body_widget = QWidget()
        body_widget.setStyleSheet("background: transparent;")
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(12)

        body.addWidget(self._mk_progress_card())
        body.addWidget(self._mk_stats_row())

        # ── Two-column area
        cols = QHBoxLayout()
        cols.setSpacing(12)
        cols.addWidget(self._mk_model_panel(), 3)
        cols.addWidget(self._mk_log_panel(), 2)
        body.addLayout(cols)

        scroll.setWidget(body_widget)
        root.addWidget(scroll, 1)

        root.addWidget(_divider())
        root.addWidget(self._mk_action_bar())

    # ── Header
    def _mk_header(self):
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_P['surface']};
                border-bottom: 1px solid {_P['border']};
            }}
        """)
        frame.setFixedHeight(58)

        lay = QHBoxLayout(frame)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(12)

        dot = QLabel("●")
        dot.setStyleSheet(f"font-size: 10px; color: {_P['accent2']}; border: none;")
        lay.addWidget(dot)

        title = QLabel("Data Sync")
        title.setObjectName("heading")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {_P['text']}; border: none;"
        )
        lay.addWidget(title)

        lay.addStretch()

        self._phase_badge = QLabel("Idle")
        self._phase_badge.setStyleSheet(f"""
            background-color: {_P['surface2']};
            border: 1px solid {_P['border2']};
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: 600;
            color: {_P['text2']};
        """)
        lay.addWidget(self._phase_badge)

        return frame

    # ── Progress card
    def _mk_progress_card(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {_P['surface']};
                border: 1px solid {_P['border']};
                border-radius: 8px;
            }}
        """)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        row = QHBoxLayout()
        lbl = QLabel("OVERALL PROGRESS")
        lbl.setObjectName("sectionTitle")
        lbl.setStyleSheet(f"color: {_P['text3']}; font-size: 10px; font-weight: 600; border: none;")
        row.addWidget(lbl)
        row.addStretch()

        self._pct_label = QLabel("0%")
        self._pct_label.setStyleSheet(
            f"color: {_P['accent2']}; font-size: 11px; font-weight: 700; border: none;"
        )
        row.addWidget(self._pct_label)
        lay.addLayout(row)

        self._main_bar = QProgressBar()
        self._main_bar.setObjectName("mainBar")
        self._main_bar.setMinimum(0)
        self._main_bar.setMaximum(100)
        self._main_bar.setValue(0)
        self._main_bar.setTextVisible(False)
        self._main_bar.setFixedHeight(24)
        lay.addWidget(self._main_bar)

        self._status_label = QLabel("Ready.")
        self._status_label.setStyleSheet(
            f"color: {_P['text2']}; font-size: 11px; border: none;"
        )
        lay.addWidget(self._status_label)

        return card

    # ── Stats row
    def _mk_stats_row(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._stat_created = StatCard("Created", "0", _P["green"])
        self._stat_updated = StatCard("Updated", "0", _P["accent2"])
        self._stat_errors  = StatCard("Errors",  "0", _P["red"])
        self._stat_elapsed = StatCard("Elapsed", "0s", _P["text2"])

        lay.addWidget(self._stat_created)
        lay.addWidget(self._stat_updated)
        lay.addWidget(self._stat_errors)
        lay.addWidget(self._stat_elapsed)

        return w

    # ── Model panel
    def _mk_model_panel(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {_P['surface']};
                border: 1px solid {_P['border']};
                border-radius: 8px;
            }}
        """)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 12, 0, 12)
        outer.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(14, 0, 14, 0)
        lbl = QLabel("MODELS")
        lbl.setObjectName("sectionTitle")
        lbl.setStyleSheet(f"color: {_P['text3']}; font-size: 10px; font-weight: 600; border: none;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._model_count = QLabel("0 / 0")
        self._model_count.setStyleSheet(
            f"color: {_P['text3']}; font-size: 10px; border: none;"
        )
        hdr.addWidget(self._model_count)
        outer.addLayout(hdr)
        outer.addWidget(_divider())

        # Scroll for model rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._model_container = QWidget()
        self._model_container.setStyleSheet("background: transparent;")
        self._model_vlayout = QVBoxLayout(self._model_container)
        self._model_vlayout.setContentsMargins(0, 4, 0, 4)
        self._model_vlayout.setSpacing(0)
        self._model_vlayout.addStretch()

        scroll.setWidget(self._model_container)
        outer.addWidget(scroll, 1)

        return card

    # ── Log panel
    def _mk_log_panel(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {_P['surface']};
                border: 1px solid {_P['border']};
                border-radius: 8px;
            }}
        """)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(14, 0, 14, 0)
        lbl = QLabel("ACTIVITY LOG")
        lbl.setObjectName("sectionTitle")
        lbl.setStyleSheet(f"color: {_P['text3']}; font-size: 10px; font-weight: 600; border: none;")
        hdr.addWidget(lbl)
        hdr.addStretch()

        clr = QPushButton("Clear")
        clr.setObjectName("btnGhost")
        clr.setFixedHeight(22)
        clr.clicked.connect(self._clear_log)
        hdr.addWidget(clr)
        outer.addLayout(hdr)
        outer.addWidget(_divider())

        self._log = QTextEdit()
        self._log.setObjectName("logView")
        self._log.setReadOnly(True)
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_P['bg']};
                border: none;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
                padding: 8px 12px;
                font-size: 11px;
            }}
        """)
        outer.addWidget(self._log, 1)

        return card

    # ── Action bar
    def _mk_action_bar(self):
        bar = QFrame()
        bar.setFixedHeight(54)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {_P['surface']};
                border-top: 1px solid {_P['border']};
            }}
        """)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(8)

        self._btn_pause = QPushButton("⏸  Pause")
        self._btn_pause.setObjectName("btnWarn")
        self._btn_pause.setFixedHeight(32)
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_pause.setVisible(False)
        lay.addWidget(self._btn_pause)

        lay.addStretch()

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setObjectName("btnDanger")
        self._btn_cancel.setFixedHeight(32)
        self._btn_cancel.clicked.connect(self._on_cancel)
        lay.addWidget(self._btn_cancel)

        self._btn_close = QPushButton("Close")
        self._btn_close.setObjectName("btnPrimary")
        self._btn_close.setFixedHeight(32)
        self._btn_close.clicked.connect(self.accept)
        self._btn_close.setVisible(False)
        lay.addWidget(self._btn_close)

        # ── Backward-compatible aliases (old callers used cancel_btn etc.)
        self.cancel_btn = self._btn_cancel
        self.pause_btn  = self._btn_pause
        self.close_btn  = self._btn_close

        return bar

    # ─────────────────── Public API called by Worker ───────────────────

    def on_sync_started(self, data: dict):
        """Called when worker emits sync_started. Shows toast, hides self."""
        self.sync_status = SyncStatus.RUNNING
        self.start_time  = datetime.now()

        sync_type = data.get("type", "full")
        tenant    = data.get("tenant", "")

        self._phase_badge.setText("Running")
        self._phase_badge.setStyleSheet(f"""
            background-color: rgba(56, 139, 253, 0.12);
            border: 1px solid {_P['accent']};
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: 600;
            color: {_P['accent2']};
        """)

        self._log_line(f"▸ {sync_type.upper()} sync started — {tenant}", "phase")
        self._log_line(f"  {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}", "muted")

        self._elapsed_timer.start(1000)
        self._btn_pause.setVisible(True)

        # Show toast, keep dialog hidden
        self._show_toast()

        if not self._mid_sync:
            # keep hidden until completion
            pass

    def on_phase_changed(self, phase: str, message: str):
        self._phase_badge.setText(phase.capitalize())
        self._log_line(f"\n► {message}", "phase")

    def on_model_started(self, model_name: str, index: int, total: int):
        if model_name not in self.model_rows:
            row = ModelRow(model_name)
            self.model_rows[model_name] = row
            self._model_vlayout.insertWidget(self._model_vlayout.count() - 1, row)

        self.model_rows[model_name].set_running()
        self._model_count.setText(f"{index} / {total}")
        self._log_line(f"  [{index}/{total}] {model_name}", "model")

    def on_model_progress(self, model_name: str, created: int, updated: int, total: int):
        if model_name in self.model_rows:
            self.model_rows[model_name].update_progress(created, updated, total)

    def on_model_completed(self, model_name: str, created: int, updated: int):
        if model_name in self.model_rows:
            self.model_rows[model_name].set_completed(created, updated)
        self._log_line(f"  ✓ {model_name}  +{created} ~{updated}", "success")

    def on_overall_progress(self, pct: int, message: str):
        self._main_bar.setValue(pct)
        self._pct_label.setText(f"{pct}%")
        self._status_label.setText(message)

    def on_error(self, context: str, message: str):
        self._log_line(f"  ✕ {context}: {message}", "error")
        current = int(self._stat_errors._val.text())
        self._stat_errors.set_value(current + 1)
        if context in self.model_rows:
            self.model_rows[context].set_error(message)

    def on_warning(self, context: str, message: str):
        self._log_line(f"  ⚠ {context}: {message}", "warn")

    def on_sync_completed(self, success: bool, summary: dict):
        """
        Called when the worker finishes.
        • Success   → silent green toast only, dialog stays hidden.
        • Failed / Cancelled → reveal the full dialog with details.
        • If the user already opened the dialog mid-sync → always reveal.
        """
        self._elapsed_timer.stop()

        created   = summary.get("created", 0)
        updated   = summary.get("updated", 0)
        duration  = summary.get("duration", 0)
        cancelled = summary.get("cancelled", False)

        self._stat_created.set_value(created)
        self._stat_updated.set_value(updated)

        self._btn_cancel.setVisible(False)
        self._btn_pause.setVisible(False)
        self._btn_close.setVisible(True)

        # Close the "starting" toast if still visible
        if self._toast and not self._toast.isHidden():
            self._toast.close()
            self._toast = None

        if cancelled:
            self.sync_status = SyncStatus.CANCELLED
            self._phase_badge.setText("Cancelled")
            self._phase_badge.setStyleSheet(f"""
                background-color: rgba(210, 153, 34, 0.12);
                border: 1px solid {_P['yellow']};
                border-radius: 10px; padding: 2px 10px;
                font-size: 10px; font-weight: 600;
                color: {_P['yellow']};
            """)
            self._log_line(f"\n⏹  Cancelled after {duration:.1f}s", "warn")
            self._status_label.setText("Sync was cancelled.")
            self._main_bar.setValue(0)
            # Always show dialog so user sees what happened
            self._reveal()

        elif success:
            self.sync_status = SyncStatus.COMPLETED
            self._phase_badge.setText("Complete")
            self._phase_badge.setStyleSheet(f"""
                background-color: rgba(63, 185, 80, 0.12);
                border: 1px solid {_P['green2']};
                border-radius: 10px; padding: 2px 10px;
                font-size: 10px; font-weight: 600;
                color: {_P['green']};
            """)
            self._log_line(
                f"\n✔  Completed in {duration:.1f}s  —  "
                f"+{created} created  ~{updated} updated",
                "success"
            )
            self._status_label.setText(f"Completed in {duration:.1f}s")
            self._main_bar.setValue(100)
            self._main_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {_P['green']}; border-radius: 3px; }}"
            )

            if self._mid_sync:
                # User already has dialog open — update it in place, keep visible
                self._reveal()
            else:
                # Silent success: just show a brief green toast, no dialog
                sub = f"+{created} created  ·  ~{updated} updated  ·  {duration:.1f}s"
                toast = SyncToast(self.parent(), kind="success",
                                  sub_override=sub, duration_ms=3500)
                toast.show_at_bottom_right()

        else:
            self.sync_status = SyncStatus.FAILED
            error_msg = summary.get("message", summary.get("error", "Unknown error"))
            self._phase_badge.setText("Failed")
            self._phase_badge.setStyleSheet(f"""
                background-color: rgba(248, 81, 73, 0.12);
                border: 1px solid {_P['red2']};
                border-radius: 10px; padding: 2px 10px;
                font-size: 10px; font-weight: 600;
                color: {_P['red']};
            """)
            self._log_line(f"\n✕  Failed: {error_msg}", "error")
            self._status_label.setText(f"Sync failed: {error_msg}")
            self._main_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {_P['red']}; border-radius: 3px; }}"
            )
            # Always reveal on failure so user sees the error detail
            self._reveal()

    # ─────────────────── UI Helpers ───────────────────

    def _reveal(self):
        """Unlock and fade-in the dialog. The ONLY legitimate way to show it."""
        self._can_show = True
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0)
        super().show()        # bypass our own guard — this is intentional
        self.raise_()
        self.activateWindow()

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start()

    def show(self):
        """Public show() is a no-op — dialog surfaces only via _reveal()."""
        if self._can_show:
            super().show()
        # else silently ignored

    def exec(self):
        """exec() is never appropriate here — this dialog is always non-blocking."""
        if self._can_show:
            super().show()
        return 0

    def _show_toast(self):
        self._toast = SyncToast(self.parent())
        self._toast.show_at_bottom_right()

    def _log_line(self, message: str, kind: str = "normal"):
        color_map = {
            "normal":  _P["text"],
            "muted":   _P["text3"],
            "phase":   _P["purple"],
            "model":   _P["accent2"],
            "success": _P["green"],
            "error":   _P["red"],
            "warn":    _P["yellow"],
            "info":    _P["accent2"],
        }
        color = color_map.get(kind, _P["text"])
        ts    = datetime.now().strftime("%H:%M:%S")
        html  = (
            f'<span style="color:{_P["text3"]};">{ts}</span>&nbsp;'
            f'<span style="color:{color};">{message}</span>'
        )
        self._log.append(html)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        self._log.clear()

    def _tick_elapsed(self):
        if self.start_time:
            secs = int((datetime.now() - self.start_time).total_seconds())
            m, s = divmod(secs, 60)
            self._stat_elapsed.set_value(f"{m}m {s:02d}s" if m else f"{s}s")

    # ─────────────────── Controls ───────────────────

    def _toggle_pause(self):
        if self.is_paused:
            self._btn_pause.setText("⏸  Pause")
            self._log_line("▶ Resumed", "info")
            self.resume_requested.emit()
        else:
            self._btn_pause.setText("▶  Resume")
            self._log_line("⏸ Paused", "warn")
            self.pause_requested.emit()
        self.is_paused = not self.is_paused

    def _on_cancel(self):
        reply = QMessageBox(self)
        reply.setWindowTitle("Cancel sync?")
        reply.setText(
            "Stop the synchronization?\n\n"
            "Partial progress will be preserved."
        )
        reply.setStyleSheet(GLOBAL_STYLE + f"""
            QMessageBox {{
                background-color: {_P['surface']};
            }}
            QLabel {{
                color: {_P['text']};
                font-size: 12px;
            }}
        """)
        reply.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        reply.setDefaultButton(QMessageBox.StandardButton.No)
        if reply.exec() == QMessageBox.StandardButton.Yes:
            self._log_line("⏹  Cancelling…", "warn")
            self.cancel_requested.emit()

    # ─────────────────── Mid-sync manual open ───────────────────

    def show_mid_sync(self):
        """
        User chose to open the dialog while sync is still running.
        Show it immediately without waiting for completion.
        """
        self._mid_sync = True
        self._reveal()

    # ─────────────────── Allow close/defocus always ───────────────────

    def closeEvent(self, event):
        """Allow close at any time; re-arm the show guard."""
        self._can_show = False
        event.accept()

    def changeEvent(self, event):
        """Don't intercept minimize / focus-out — let it happen naturally."""
        super().changeEvent(event)


# ──────────────────────────────────────────────
# Quick demo / smoke test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout

    app = QApplication(sys.argv)

    # ── Launcher window so you can test both paths ──
    launcher = QWidget()
    launcher.setWindowTitle("Sync Demo")
    launcher.setStyleSheet(GLOBAL_STYLE)
    launcher.resize(300, 100)
    lay = QVBoxLayout(launcher)

    def run_sync(succeed: bool):
        dlg = DetailedSyncDialog()
        models = ["Customer", "Invoice", "Product", "Payment", "TaxRate"]
        step = [0]

        def simulate():
            s = step[0]
            n_models = len(models)
            if s == 0:
                dlg.on_sync_started({"type": "full", "tenant": "demo_corp"})
            elif s == 1:
                dlg.on_phase_changed("download", "📥 Downloading changes")
                dlg.on_overall_progress(15, "Downloading…")
            elif 2 <= s < 2 + n_models:
                i = s - 2
                m = models[i]
                dlg.on_model_started(m, i + 1, n_models)
                dlg.on_model_progress(m, i * 6, i * 3, 80)
                dlg.on_overall_progress(15 + int((i / n_models) * 75), f"Applying {m}…")
                dlg.on_model_completed(m, i * 6, i * 3)
            elif s == 2 + n_models:
                dlg.on_overall_progress(98, "Finalising…")
            elif s == 2 + n_models + 1:
                if succeed:
                    # ✅ Silent — only a green toast appears, no dialog
                    dlg.on_sync_completed(True, {
                        "duration": 8.7, "created": 60, "updated": 30,
                    })
                else:
                    # ❌ Failure — full dialog appears automatically
                    dlg.on_error("Invoice", "Foreign key constraint failed")
                    dlg.on_sync_completed(False, {
                        "duration": 5.2,
                        "error": "db_error",
                        "message": "Foreign key constraint failed on Invoice",
                    })
                t.stop()
                return
            step[0] += 1

        t = QTimer()
        t.timeout.connect(simulate)
        t.start(800)
        # Keep timer alive
        launcher._timers = getattr(launcher, "_timers", [])
        launcher._timers.append(t)

    btn_ok = QPushButton("▶  Simulate SUCCESS (silent)")
    btn_ok.setObjectName("btnPrimary")
    btn_ok.clicked.connect(lambda: run_sync(True))
    lay.addWidget(btn_ok)

    btn_fail = QPushButton("▶  Simulate FAILURE (dialog pops up)")
    btn_fail.setObjectName("btnDanger")
    btn_fail.clicked.connect(lambda: run_sync(False))
    lay.addWidget(btn_fail)

    launcher.show()
    sys.exit(app.exec())

    sys.exit(app.exec())