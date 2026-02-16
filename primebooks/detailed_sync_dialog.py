"""
Detailed Sync Progress Dialog - Rich interactive UI
✅ Real-time progress tracking
✅ Model-by-model breakdown
✅ Expandable details
✅ Color-coded status
✅ Error/warning display
"""
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTextEdit, QGroupBox, QScrollArea, QWidget,
    QListWidget, QListWidgetItem, QSplitter
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor
from datetime import datetime

logger = logging.getLogger(__name__)


class DetailedSyncDialog(QDialog):
    """
    Non-modal dialog showing detailed sync progress
    User can minimize and continue working
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔄 Data Synchronization")
        self.resize(800, 600)

        # Make it non-modal so user can interact with app
        self.setModal(False)

        # Keep on top but not blocking
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.start_time = None
        self.model_items = {}  # {model_name: QListWidgetItem}

        self.setup_ui()

    def setup_ui(self):
        """Setup the UI components"""
        layout = QVBoxLayout()

        # =============================
        # HEADER SECTION
        # =============================
        header = self._create_header()
        layout.addWidget(header)

        # =============================
        # PROGRESS SECTION
        # =============================
        progress_group = self._create_progress_section()
        layout.addWidget(progress_group)

        # =============================
        # DETAILS SECTION (Splitter)
        # =============================
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Model list
        model_section = self._create_model_list()
        splitter.addWidget(model_section)

        # Right: Logs/Details
        log_section = self._create_log_section()
        splitter.addWidget(log_section)

        splitter.setStretchFactor(0, 3)  # Models take 60%
        splitter.setStretchFactor(1, 2)  # Logs take 40%

        layout.addWidget(splitter, stretch=1)

        # =============================
        # FOOTER SECTION
        # =============================
        footer = self._create_footer()
        layout.addWidget(footer)

        self.setLayout(layout)

    def _create_header(self):
        """Create header with title and status"""
        header = QWidget()
        layout = QVBoxLayout()

        # Title
        title = QLabel("🔄 Synchronizing Data")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Current phase
        self.phase_label = QLabel("Initializing...")
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("color: #3498db; font-size: 14px; margin: 5px;")
        layout.addWidget(self.phase_label)

        header.setLayout(layout)
        return header

    def _create_progress_section(self):
        """Create overall progress section"""
        group = QGroupBox("Overall Progress")
        layout = QVBoxLayout()

        # Main progress bar
        self.main_progress = QProgressBar()
        self.main_progress.setMinimum(0)
        self.main_progress.setMaximum(100)
        self.main_progress.setValue(0)
        self.main_progress.setTextVisible(True)
        self.main_progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                text-align: center;
                height: 30px;
                font-size: 14px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2ecc71);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.main_progress)

        # Status message
        self.status_label = QLabel("Ready to sync...")
        self.status_label.setStyleSheet("font-size: 13px; margin-top: 5px;")
        layout.addWidget(self.status_label)

        # Stats row
        stats_layout = QHBoxLayout()

        self.created_label = QLabel("Created: 0")
        self.created_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        stats_layout.addWidget(self.created_label)

        self.updated_label = QLabel("Updated: 0")
        self.updated_label.setStyleSheet("color: #2980b9; font-weight: bold;")
        stats_layout.addWidget(self.updated_label)

        self.errors_label = QLabel("Errors: 0")
        self.errors_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        stats_layout.addWidget(self.errors_label)

        self.time_label = QLabel("Time: 0s")
        self.time_label.setStyleSheet("color: #7f8c8d; font-weight: bold;")
        stats_layout.addWidget(self.time_label)

        stats_layout.addStretch()

        layout.addLayout(stats_layout)

        group.setLayout(layout)
        return group

    def _create_model_list(self):
        """Create model-by-model progress list"""
        group = QGroupBox("Model Progress")
        layout = QVBoxLayout()

        self.model_list = QListWidget()
        self.model_list.setAlternatingRowColors(True)
        self.model_list.setStyleSheet("""
            QListWidget {
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 5px;
            }
        """)

        layout.addWidget(self.model_list)

        group.setLayout(layout)
        return group

    def _create_log_section(self):
        """Create log/details section"""
        group = QGroupBox("Activity Log")
        layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #2c3e50;
                color: #ecf0f1;
                font-family: 'Courier New', monospace;
                font-size: 11px;
            }
        """)

        layout.addWidget(self.log_text)

        group.setLayout(layout)
        return group

    def _create_footer(self):
        """Create footer with action buttons"""
        footer = QWidget()
        layout = QHBoxLayout()

        # Minimize button
        self.minimize_btn = QPushButton("⬇️ Minimize")
        self.minimize_btn.clicked.connect(self.showMinimized)
        self.minimize_btn.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        layout.addWidget(self.minimize_btn)

        layout.addStretch()

        # Cancel button (only during sync)
        self.cancel_btn = QPushButton("⏹️ Cancel Sync")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        layout.addWidget(self.cancel_btn)

        # Close button (after sync)
        self.close_btn = QPushButton("✓ Close")
        self.close_btn.setVisible(False)
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        layout.addWidget(self.close_btn)

        footer.setLayout(layout)
        return footer

    # =============================
    # UPDATE METHODS
    # =============================

    def on_sync_started(self, data):
        """Handle sync started"""
        self.start_time = datetime.now()
        self.add_log(f"🚀 Sync started: {data.get('type', 'unknown')} sync")
        self.add_log(f"   Tenant: {data.get('tenant', 'unknown')}")

        # Start timer for elapsed time
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_elapsed_time)
        self.timer.start(1000)  # Update every second

    def on_phase_changed(self, phase, message):
        """Handle phase change"""
        self.phase_label.setText(f"📍 {message}")
        self.add_log(f"\n{'='*60}")
        self.add_log(f"📍 PHASE: {phase.upper()}")
        self.add_log(f"{'='*60}")

    def on_model_started(self, model_name, index, total):
        """Handle model sync started"""
        # Add to model list
        item = QListWidgetItem(f"⏳ {model_name} - Starting...")
        item.setForeground(QColor("#f39c12"))  # Orange
        self.model_list.addItem(item)
        self.model_items[model_name] = item

        # Scroll to bottom
        self.model_list.scrollToBottom()

        self.add_log(f"  📦 [{index}/{total}] {model_name} - Starting...")

    def on_model_progress(self, model_name, created, updated, total):
        """Handle model progress update"""
        if model_name in self.model_items:
            item = self.model_items[model_name]
            item.setText(f"⚙️ {model_name} - {created}C, {updated}U of {total}")
            item.setForeground(QColor("#3498db"))  # Blue

    def on_model_completed(self, model_name, created, updated):
        """Handle model completion"""
        if model_name in self.model_items:
            item = self.model_items[model_name]
            item.setText(f"✓ {model_name} - Created: {created}, Updated: {updated}")
            item.setForeground(QColor("#27ae60"))  # Green

        self.add_log(f"  ✓ {model_name} - Created: {created}, Updated: {updated}")

    def on_overall_progress(self, percentage, message):
        """Handle overall progress update"""
        self.main_progress.setValue(percentage)
        self.status_label.setText(message)

    def on_error(self, context, message):
        """Handle error"""
        self.add_log(f"  ❌ ERROR in {context}: {message}", color="red")

        # Update error count
        current = int(self.errors_label.text().split(":")[1].strip())
        self.errors_label.setText(f"Errors: {current + 1}")

    def on_warning(self, context, message):
        """Handle warning"""
        self.add_log(f"  ⚠️ WARNING in {context}: {message}", color="yellow")

    def on_sync_completed(self, success, summary):
        """Handle sync completion"""
        if self.timer:
            self.timer.stop()

        self.add_log(f"\n{'='*60}")

        if success:
            self.phase_label.setText("✅ Sync Completed Successfully!")
            self.phase_label.setStyleSheet("color: #27ae60; font-size: 14px; margin: 5px;")
            self.add_log("✅ SYNC COMPLETED SUCCESSFULLY!", color="green")

            duration = summary.get('duration', 0)
            self.add_log(f"   Duration: {duration:.1f}s")
            self.add_log(f"   Created: {summary.get('created', 0)}")
            self.add_log(f"   Updated: {summary.get('updated', 0)}")

        else:
            self.phase_label.setText("❌ Sync Failed")
            self.phase_label.setStyleSheet("color: #e74c3c; font-size: 14px; margin: 5px;")
            self.add_log("❌ SYNC FAILED!", color="red")

            if 'error' in summary:
                self.add_log(f"   Error: {summary['error']}")
            if 'message' in summary:
                self.add_log(f"   Message: {summary['message']}")

        self.add_log(f"{'='*60}")

        # Update UI
        self.cancel_btn.setVisible(False)
        self.close_btn.setVisible(True)

        # Update final stats
        self.created_label.setText(f"Created: {summary.get('created', 0)}")
        self.updated_label.setText(f"Updated: {summary.get('updated', 0)}")

    def update_elapsed_time(self):
        """Update elapsed time display"""
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.time_label.setText(f"Time: {int(elapsed)}s")

            # Also update stats from current values
            # (These would be updated by signal handlers in real implementation)

    def add_log(self, message, color=None):
        """Add message to log"""
        if color:
            color_map = {
                'red': '#e74c3c',
                'green': '#27ae60',
                'yellow': '#f39c12',
                'blue': '#3498db',
            }
            html_color = color_map.get(color, '#ecf0f1')
            self.log_text.append(f'<span style="color: {html_color};">{message}</span>')
        else:
            self.log_text.append(message)

        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())