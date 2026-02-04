# primebooks/sync_scheduler.py
"""
Automatic sync scheduler
✅ Prompts user daily: "PrimeBooks wants to sync data online. Allow or Cancel"
✅ Manual sync on demand
✅ Background sync without blocking UI
"""
from PyQt6.QtCore import QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SyncScheduler:
    """
    Manages automatic sync scheduling
    ✅ Daily sync prompts
    ✅ Manual sync
    """

    def __init__(self, main_window, tenant_id, schema_name, auth_token):
        self.main_window = main_window
        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self.auth_token = auth_token

        # Timer for checking if sync needed
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_if_sync_needed)

        # Check every hour
        self.check_timer.start(3600000)  # 1 hour = 3,600,000 ms

        # Also check on startup (after 1 minute)
        QTimer.singleShot(60000, self.check_if_sync_needed)

        logger.info("✅ Sync scheduler initialized")

    def check_if_sync_needed(self):
        """Check if it's time to prompt for sync"""
        try:
            from primebooks.sync import SyncManager

            sync_manager = SyncManager(
                tenant_id=self.tenant_id,
                schema_name=self.schema_name,
                auth_token=self.auth_token
            )

            # Check if server is online
            if not sync_manager.is_online():
                logger.debug("Server not reachable - skipping sync check")
                return

            # Check if should sync
            if sync_manager.should_auto_sync():
                logger.info("📅 Time for automatic sync - prompting user")
                self.prompt_user_for_sync()

        except Exception as e:
            logger.error(f"Error checking sync: {e}")

    def prompt_user_for_sync(self):
        """
        Show dialog: "PrimeBooks wants to sync data online. Allow or Cancel"
        """
        reply = QMessageBox.question(
            self.main_window,
            'Sync Data',
            'PrimeBooks wants to sync your data online.\n\n'
            'This will upload any offline changes and download updates from the server.\n\n'
            'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply == QMessageBox.StandardButton.Yes:
            logger.info("✅ User allowed automatic sync")
            self.start_sync()
        else:
            logger.info("❌ User cancelled automatic sync")

    def start_sync(self):
        """Start sync in background"""
        from primebooks.sync_dialogs import SyncProgressDialog

        # Show progress dialog
        sync_dialog = SyncProgressDialog(
            self.main_window,
            self.tenant_id,
            self.schema_name,
            self.auth_token,
            is_first_sync=False
        )

        sync_dialog.exec()

    def stop(self):
        """Stop scheduler"""
        self.check_timer.stop()
        logger.info("Sync scheduler stopped")