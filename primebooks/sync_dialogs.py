# primebooks/sync_dialogs.py
"""
Sync UI dialogs
✅ Progress dialog with detailed status
✅ Manual sync dialog
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
import logging

logger = logging.getLogger(__name__)


class SyncThread(QThread):
    """Background sync thread"""
    progress_update = pyqtSignal(str, int)
    sync_complete = pyqtSignal(bool, str)

    def __init__(self, tenant_id, schema_name, auth_token, is_first_sync=False):
        super().__init__()
        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self.auth_token = auth_token
        self.is_first_sync = is_first_sync

    def run(self):
        """Run sync"""
        try:
            from primebooks.sync import SyncManager

            self.progress_update.emit("Initializing sync...", 5)

            sync_manager = SyncManager(
                tenant_id=self.tenant_id,
                schema_name=self.schema_name,
                auth_token=self.auth_token
            )

            # Progress callback
            def progress_callback(message, percentage):
                self.progress_update.emit(message, percentage)

            # Run sync
            success = sync_manager.full_sync(
                is_first_sync=self.is_first_sync,
                progress_callback=progress_callback
            )

            if success:
                self.sync_complete.emit(True, "Sync completed successfully")
            else:
                self.sync_complete.emit(False, "Sync failed - check logs")

        except Exception as e:
            logger.error(f"Sync error: {e}", exc_info=True)
            self.sync_complete.emit(False, f"Sync error: {str(e)}")


class SyncProgressDialog(QDialog):
    """
    Progress dialog for sync operations
    Shows detailed progress with status messages
    """

    def __init__(self, parent, tenant_id, schema_name, auth_token, is_first_sync=False):
        super().__init__(parent)
        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self.auth_token = auth_token
        self.is_first_sync = is_first_sync

        self.setWindowTitle("Syncing Data")
        self.setFixedSize(450, 150)
        self.setModal(True)

        self.setup_ui()

        # Start sync after dialog shown
        QTimer.singleShot(100, self.start_sync)

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        if self.is_first_sync:
            title = QLabel("<h3>Initial Data Download</h3>")
        else:
            title = QLabel("<h3>Syncing Your Data</h3>")

        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Status label
        self.status_label = QLabel("Preparing to sync...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def start_sync(self):
        """Start sync in background thread"""
        self.sync_thread = SyncThread(
            self.tenant_id,
            self.schema_name,
            self.auth_token,
            self.is_first_sync
        )

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
            self.status_label.setText("✅ Sync complete!")
            self.progress_bar.setValue(100)
            QTimer.singleShot(500, self.accept)
        else:
            QMessageBox.warning(
                self,
                "Sync Failed",
                f"{message}\n\nYou can try again later or continue working offline."
            )
            self.reject()


class ManualSyncDialog(QDialog):
    """
    Manual sync trigger dialog
    Allows user to manually sync at any time
    """

    def __init__(self, parent, tenant_id, schema_name, auth_token):
        super().__init__(parent)
        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self.auth_token = auth_token

        self.setWindowTitle("Sync Data")
        self.setFixedSize(400, 200)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h3>Sync Data with Server</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "This will:\n"
            "• Upload any offline changes to the server\n"
            "• Download updates from the server\n"
            "• Ensure your data is up to date"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Sync button
        sync_btn = QPushButton("Start Sync")
        sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        sync_btn.clicked.connect(self.start_sync)
        layout.addWidget(sync_btn)

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        self.setLayout(layout)

    def start_sync(self):
        """Start sync"""
        self.accept()

        # Show progress dialog
        sync_dialog = SyncProgressDialog(
            self.parent(),
            self.tenant_id,
            self.schema_name,
            self.auth_token,
            is_first_sync=False
        )

        sync_dialog.exec()