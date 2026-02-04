# primebooks/ui/sync_dialogs.py
"""
Sync UI Components for Desktop App
✅ Automatic sync detection
✅ User prompt for sync
✅ Manual sync button
✅ Background sync with progress
✅ Connection status monitoring
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox, QCheckBox, QGroupBox
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QIcon
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# AUTO SYNC PROMPT DIALOG
# ============================================================================

class AutoSyncPromptDialog(QDialog):
    """
    Dialog that appears when connection is detected
    ✅ Asks user if they want to sync
    ✅ Shows pending changes count
    """

    def __init__(self, pending_changes_count=0, parent=None):
        super().__init__(parent)
        self.pending_changes_count = pending_changes_count
        self.should_sync = False

        self.setWindowTitle("Sync Available")
        self.setFixedWidth(450)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Icon and title
        title = QLabel("<h2>🌐 Connection Detected!</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #27ae60; margin: 20px 0;")
        layout.addWidget(title)

        # Message
        if self.pending_changes_count > 0:
            message = QLabel(
                f"You have <b>{self.pending_changes_count} offline changes</b> ready to sync.\n\n"
                "Would you like to sync now?"
            )
        else:
            message = QLabel(
                "Your app is now online.\n\n"
                "Would you like to sync your data with the server?"
            )

        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        message.setStyleSheet("margin: 10px 0; font-size: 14px;")
        layout.addWidget(message)

        # Info box
        info_box = QGroupBox("What will happen:")
        info_layout = QVBoxLayout()

        info_items = [
            "✓ Your offline changes will be uploaded to the server",
            "✓ Fresh data will be downloaded from the server",
            "✓ Your local database will be updated",
            "✓ Sync happens in the background"
        ]

        for item in info_items:
            label = QLabel(item)
            label.setStyleSheet("margin: 5px 0;")
            info_layout.addWidget(label)

        info_box.setLayout(info_layout)
        info_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #bdc3c7;
                border-radius: 5px;
                margin-top: 10px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        layout.addWidget(info_box)

        # Auto-sync checkbox
        self.auto_sync_checkbox = QCheckBox("Always sync automatically (don't ask again)")
        self.auto_sync_checkbox.setStyleSheet("margin: 10px 0;")
        layout.addWidget(self.auto_sync_checkbox)

        layout.addSpacing(20)

        # Buttons
        button_layout = QHBoxLayout()

        self.sync_btn = QPushButton("Sync Now")
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 12px 30px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        self.sync_btn.clicked.connect(self.accept_sync)

        self.later_btn = QPushButton("Sync Later")
        self.later_btn.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                border: none;
                padding: 12px 30px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        self.later_btn.clicked.connect(self.reject)

        button_layout.addWidget(self.later_btn)
        button_layout.addWidget(self.sync_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def accept_sync(self):
        """User chose to sync"""
        self.should_sync = True
        self.accept()

    def get_auto_sync_preference(self):
        """Get auto-sync preference"""
        return self.auto_sync_checkbox.isChecked()


# ============================================================================
# SYNC PROGRESS DIALOG
# ============================================================================

class SyncProgressDialog(QDialog):
    """
    Dialog showing sync progress
    ✅ Runs sync in background thread
    ✅ Shows detailed progress
    """

    def __init__(self, sync_manager, sync_type='full', parent=None):
        """
        Args:
            sync_manager: SyncManager instance
            sync_type: 'full', 'upload', or 'download'
        """
        super().__init__(parent)
        self.sync_manager = sync_manager
        self.sync_type = sync_type

        self.setWindowTitle("Syncing Data")
        self.setFixedSize(500, 200)
        self.setModal(True)

        self.setup_ui()

        # Start sync after dialog shown
        QTimer.singleShot(100, self.start_sync)

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>🔄 Syncing Your Data</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("margin-bottom: 20px;")
        layout.addWidget(title)

        # Status label
        self.status_label = QLabel("Preparing to sync...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; margin: 10px 0;")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Details label
        self.details_label = QLabel("")
        self.details_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_label.setStyleSheet("color: #7f8c8d; margin-top: 10px;")
        layout.addWidget(self.details_label)

        self.setLayout(layout)

    def start_sync(self):
        """Start sync in background thread"""
        self.sync_thread = SyncThread(self.sync_manager, self.sync_type)
        self.sync_thread.progress_update.connect(self.update_progress)
        self.sync_thread.sync_complete.connect(self.on_sync_complete)
        self.sync_thread.start()

    def update_progress(self, message, percentage):
        """Update progress display"""
        self.status_label.setText(message)
        self.progress_bar.setValue(percentage)

    def on_sync_complete(self, success, message):
        """Handle sync completion"""
        if success:
            self.status_label.setText("✓ Sync complete!")
            self.progress_bar.setValue(100)
            self.details_label.setText(message)

            # Close after brief delay
            QTimer.singleShot(1000, self.accept)
        else:
            self.status_label.setText("✗ Sync failed")
            self.details_label.setText(message)
            self.details_label.setStyleSheet("color: #e74c3c; margin-top: 10px;")

            # Show error details
            QMessageBox.warning(
                self,
                "Sync Failed",
                f"{message}\n\nYou can try again later or check the logs for details."
            )
            self.reject()


# ============================================================================
# SYNC THREAD
# ============================================================================

class SyncThread(QThread):
    """Background thread for syncing"""
    progress_update = pyqtSignal(str, int)
    sync_complete = pyqtSignal(bool, str)

    def __init__(self, sync_manager, sync_type='full'):
        super().__init__()
        self.sync_manager = sync_manager
        self.sync_type = sync_type

    def run(self):
        """Run sync operation"""
        try:
            if self.sync_type == 'full':
                # Full bidirectional sync
                success, message = self.sync_manager.full_sync(
                    is_first_sync=False,
                    progress_callback=self.progress_update.emit
                )
            elif self.sync_type == 'upload':
                # Upload only
                success, message = self.sync_manager.upload_offline_changes(
                    progress_callback=self.progress_update.emit
                )
            elif self.sync_type == 'download':
                # Download only
                success, message = self.sync_manager.download_all_data(
                    progress_callback=self.progress_update.emit
                )
            else:
                success = False
                message = f"Unknown sync type: {self.sync_type}"

            self.sync_complete.emit(success, message)

        except Exception as e:
            logger.error(f"Sync thread error: {e}", exc_info=True)
            self.sync_complete.emit(False, f"Sync error: {str(e)}")


# ============================================================================
# MANUAL SYNC DIALOG
# ============================================================================

class ManualSyncDialog(QDialog):
    """
    Manual sync dialog with options
    ✅ Choose sync direction
    ✅ View sync status
    """

    def __init__(self, sync_manager, parent=None):
        super().__init__(parent)
        self.sync_manager = sync_manager

        self.setWindowTitle("Manual Sync")
        self.setFixedWidth(450)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>Manual Sync</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("margin-bottom: 20px;")
        layout.addWidget(title)

        # Status info
        status_group = QGroupBox("Current Status")
        status_layout = QVBoxLayout()

        # Connection status
        is_online = self.sync_manager.is_online()
        connection_label = QLabel(
            f"Connection: {'🟢 Online' if is_online else '🔴 Offline'}"
        )
        connection_label.setStyleSheet("font-size: 14px; margin: 5px 0;")
        status_layout.addWidget(connection_label)

        # Last sync
        last_sync = self.sync_manager.get_last_sync_time()
        if last_sync:
            last_sync_str = last_sync.strftime('%Y-%m-%d %H:%M:%S')
            last_sync_label = QLabel(f"Last sync: {last_sync_str}")
        else:
            last_sync_label = QLabel("Last sync: Never")
        last_sync_label.setStyleSheet("font-size: 14px; margin: 5px 0;")
        status_layout.addWidget(last_sync_label)

        # Pending changes
        pending_count = self.sync_manager.get_pending_changes_count()
        pending_label = QLabel(f"Pending changes: {pending_count}")
        pending_label.setStyleSheet("font-size: 14px; margin: 5px 0;")
        status_layout.addWidget(pending_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addSpacing(20)

        # Sync options
        if is_online:
            # Full sync button
            full_sync_btn = QPushButton("🔄 Full Sync (Upload & Download)")
            full_sync_btn.setStyleSheet(self._button_style("#3498db"))
            full_sync_btn.clicked.connect(lambda: self.start_sync('full'))
            layout.addWidget(full_sync_btn)

            # Upload only button
            upload_btn = QPushButton("🔼 Upload Changes Only")
            upload_btn.setStyleSheet(self._button_style("#27ae60"))
            upload_btn.clicked.connect(lambda: self.start_sync('upload'))
            layout.addWidget(upload_btn)

            # Download only button
            download_btn = QPushButton("🔽 Download Data Only")
            download_btn.setStyleSheet(self._button_style("#9b59b6"))
            download_btn.clicked.connect(lambda: self.start_sync('download'))
            layout.addWidget(download_btn)
        else:
            offline_label = QLabel("⚠️ Cannot sync - Server not reachable")
            offline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            offline_label.setStyleSheet("color: #e74c3c; font-size: 14px; margin: 20px 0;")
            layout.addWidget(offline_label)

        layout.addSpacing(20)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(self._button_style("#95a5a6"))
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

        self.setLayout(layout)

    def _button_style(self, color):
        """Get button style with color"""
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                padding: 12px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                margin: 5px 0;
            }}
            QPushButton:hover {{
                opacity: 0.8;
            }}
        """

    def start_sync(self, sync_type):
        """Start selected sync type"""
        self.accept()

        # Show progress dialog
        progress_dialog = SyncProgressDialog(
            self.sync_manager,
            sync_type=sync_type,
            parent=self.parent()
        )
        progress_dialog.exec()


# ============================================================================
# CONNECTION MONITOR
# ============================================================================

class ConnectionMonitor(QThread):
    """
    Background thread that monitors connection status
    ✅ Detects when connection is restored
    ✅ Triggers auto-sync prompt
    """
    connection_restored = pyqtSignal()
    connection_lost = pyqtSignal()

    def __init__(self, sync_manager, check_interval=30):
        """
        Args:
            sync_manager: SyncManager instance
            check_interval: Seconds between checks
        """
        super().__init__()
        self.sync_manager = sync_manager
        self.check_interval = check_interval
        self.was_online = False
        self.running = True

    def run(self):
        """Monitor connection status"""
        while self.running:
            try:
                is_online = self.sync_manager.is_online()

                # Check for state change
                if is_online and not self.was_online:
                    # Connection restored!
                    logger.info("🌐 Connection restored!")
                    self.connection_restored.emit()
                elif not is_online and self.was_online:
                    # Connection lost
                    logger.info("📡 Connection lost")
                    self.connection_lost.emit()

                self.was_online = is_online

                # Wait before next check
                self.msleep(self.check_interval * 1000)

            except Exception as e:
                logger.error(f"Connection monitor error: {e}")
                self.msleep(self.check_interval * 1000)

    def stop(self):
        """Stop monitoring"""
        self.running = False