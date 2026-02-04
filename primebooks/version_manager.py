# primebooks/version_manager.py
"""
Version Selection and Rollback Manager
✅ Users can choose specific version
✅ Admin can force rollback
✅ Version lifecycle display
"""
import requests
import logging
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                             QListWidget, QMessageBox, QTextEdit)
from PyQt6.QtCore import Qt
from django.conf import settings

logger = logging.getLogger(__name__)


class VersionSelectorDialog(QDialog):
    """
    Let user choose which version to install
    Shows all available versions with lifecycle status
    """

    def __init__(self, parent, versions, current_version):
        super().__init__(parent)
        self.versions = versions
        self.current_version = current_version
        self.selected_version = None

        self.setWindowTitle("Choose PrimeBooks Version")
        self.setFixedSize(500, 400)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>Select Version to Install</h2>")
        layout.addWidget(title)

        # Current version
        current = QLabel(f"<b>Current Version:</b> {self.current_version}")
        layout.addWidget(current)

        # Version list
        list_label = QLabel("<b>Available Versions:</b>")
        layout.addWidget(list_label)

        self.version_list = QListWidget()

        for version in self.versions:
            status = self.get_status_label(version)
            item_text = f"v{version['version']} - {status}"
            self.version_list.addItem(item_text)

        self.version_list.currentRowChanged.connect(self.on_version_selected)
        layout.addWidget(self.version_list)

        # Release notes
        notes_label = QLabel("<b>Release Notes:</b>")
        layout.addWidget(notes_label)

        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setMaximumHeight(100)
        layout.addWidget(self.notes_text)

        # Install button
        install_btn = QPushButton("Install Selected Version")
        install_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 10px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        install_btn.clicked.connect(self.install_version)
        layout.addWidget(install_btn)

        # Cancel
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        self.setLayout(layout)

        # Select first
        if self.versions:
            self.version_list.setCurrentRow(0)

    def get_status_label(self, version):
        """Get status label for version"""
        if version.get('is_latest'):
            return "Latest"
        elif version.get('lifecycle_status') == 'stable':
            return "Stable"
        elif version.get('lifecycle_status') == 'deprecated':
            return "⚠️ Deprecated"
        elif version.get('lifecycle_status') == 'eol':
            return "❌ EOL"
        else:
            return "Available"

    def on_version_selected(self, index):
        """Update notes when version selected"""
        if 0 <= index < len(self.versions):
            version = self.versions[index]
            notes = version.get('release_notes', 'No notes')

            if len(notes) > 200:
                notes = notes[:200] + "..."

            self.notes_text.setPlainText(notes)

    def install_version(self):
        """Install selected version"""
        index = self.version_list.currentRow()

        if index >= 0:
            self.selected_version = self.versions[index]

            # Warn if deprecated
            if self.selected_version.get('lifecycle_status') == 'deprecated':
                reply = QMessageBox.warning(
                    self,
                    "Deprecated Version",
                    "This version is deprecated.\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.No:
                    return

            self.accept()


class ForcedRollbackDialog(QDialog):
    """Dialog for forced rollback"""

    def __init__(self, parent, rollback_info):
        super().__init__(parent)
        self.rollback_info = rollback_info

        self.setWindowTitle("⚠️ Rollback Required")
        self.setFixedSize(500, 300)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Warning
        title = QLabel("<h2>⚠️ Critical Rollback Required</h2>")
        title.setStyleSheet("color: #e74c3c;")
        layout.addWidget(title)

        # Message
        current = self.rollback_info.get('current_version')
        target = self.rollback_info.get('target_version')
        reason = self.rollback_info.get('reason', 'Critical issues')

        message = QLabel(
            f"<b>Issue found in version {current}.</b><br><br>"
            f"{reason}<br><br>"
            f"Rolling back to version {target}."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        # Rollback button
        btn = QPushButton("Rollback Now")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 12px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

        self.setLayout(layout)


class VersionManager:
    """Manages version selection and rollback"""

    def __init__(self, main_window, server_url, auth_token):
        self.main_window = main_window
        self.server_url = server_url
        self.auth_token = auth_token

    def get_available_versions(self):
        """Get all available versions"""
        try:
            url = f"{self.server_url}/api/desktop/versions/available/"

            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('versions', [])

            return []

        except Exception as e:
            logger.error(f"Error fetching versions: {e}")
            return []

    def show_version_selector(self, current_version):
        """Show version selection dialog"""
        versions = self.get_available_versions()

        if not versions:
            QMessageBox.warning(
                self.main_window,
                "No Versions",
                "Could not load versions from server."
            )
            return None

        dialog = VersionSelectorDialog(
            self.main_window,
            versions,
            current_version
        )

        if dialog.exec():
            return dialog.selected_version

        return None

    def check_for_rollback(self, current_version):
        """Check if rollback required"""
        try:
            url = f"{self.server_url}/api/desktop/check-rollback/"

            response = requests.get(
                url,
                params={'current_version': current_version},
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()

                if data.get('rollback_required'):
                    return data

            return None

        except Exception as e:
            logger.error(f"Error checking rollback: {e}")
            return None

    def perform_rollback(self, rollback_info):
        """Execute rollback"""
        dialog = ForcedRollbackDialog(self.main_window, rollback_info)

        if dialog.exec():
            target_version = rollback_info.get('target_version_data')

            if target_version:
                from primebooks.updater import UpdateManager

                update_manager = UpdateManager(
                    self.main_window,
                    self.server_url,
                    self.auth_token
                )

                update_manager.download_and_install_update(target_version)