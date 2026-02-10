# primebooks/update_manager.py
"""
Auto-Update System for PrimeBooks Desktop
✅ Checks for updates from server
✅ Notifies users of available updates
✅ Downloads and installs updates
"""
import requests
import logging
import subprocess
import sys
import platform
from pathlib import Path
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar
from django.conf import settings

logger = logging.getLogger(__name__)

# Current version - UPDATE THIS WHEN RELEASING
CURRENT_VERSION = "1.0.0"


def parse_version(version_string):
    """Parse version string to tuple for comparison"""
    try:
        return tuple(map(int, version_string.split('.')))
    except:
        return (0, 0, 0)


# ============================================================================
# UPDATE CHECKER (Background Thread)
# ============================================================================

class UpdateChecker(QThread):
    """Background thread to check for updates"""
    update_available = pyqtSignal(dict)  # Emits update info
    no_updates = pyqtSignal()
    check_failed = pyqtSignal(str)

    def __init__(self, server_url, auth_token):
        super().__init__()
        self.server_url = server_url
        self.auth_token = auth_token

    def run(self):
        """Check for updates"""
        try:
            logger.info(f"🔍 Checking for updates (current: {CURRENT_VERSION})...")

            url = f"{self.server_url}/api/desktop/updates/check/"

            response = requests.get(
                url,
                params={'current_version': CURRENT_VERSION},
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=10
            )

            if response.status_code != 200:
                self.check_failed.emit(f"Server returned {response.status_code}")
                return

            data = response.json()

            if data.get('update_available'):
                logger.info(f"✅ Update available: {data.get('latest_version')}")
                self.update_available.emit(data)
            else:
                logger.info("✅ No updates available")
                self.no_updates.emit()

        except requests.exceptions.ConnectionError:
            logger.debug("Server not reachable for update check")
            self.check_failed.emit("Server not reachable")

        except Exception as e:
            logger.error(f"Update check failed: {e}")
            self.check_failed.emit(str(e))


# ============================================================================
# UPDATE DOWNLOADER (Background Thread)
# ============================================================================

class UpdateDownloader(QThread):
    """Downloads update in background"""
    progress = pyqtSignal(int)  # Download progress (0-100)
    download_complete = pyqtSignal(str)  # Path to downloaded file
    download_failed = pyqtSignal(str)

    def __init__(self, download_url, auth_token):
        super().__init__()
        self.download_url = download_url
        self.auth_token = auth_token

        # Determine file extension
        if platform.system() == 'Windows':
            filename = 'PrimeBooks_Update.exe'
        elif platform.system() == 'Darwin':
            filename = 'PrimeBooks_Update.dmg'
        else:
            filename = 'PrimeBooks_Update.AppImage'

        self.download_path = settings.DESKTOP_DATA_DIR / 'updates' / filename

    def run(self):
        """Download update"""
        try:
            logger.info(f"📥 Downloading update from {self.download_url}")

            # Create updates directory
            self.download_path.parent.mkdir(parents=True, exist_ok=True)

            # Download with progress
            response = requests.get(
                self.download_url,
                headers={'Authorization': f'Bearer {self.auth_token}'},
                stream=True,
                timeout=300
            )

            if response.status_code != 200:
                self.download_failed.emit(f"Download failed: HTTP {response.status_code}")
                return

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(self.download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            self.progress.emit(progress)

            logger.info(f"✅ Update downloaded: {self.download_path}")
            self.download_complete.emit(str(self.download_path))

        except Exception as e:
            logger.error(f"Download failed: {e}")
            self.download_failed.emit(str(e))


# ============================================================================
# UPDATE DIALOGS
# ============================================================================

class UpdateAvailableDialog(QDialog):
    """Dialog shown when update is available"""

    def __init__(self, parent, update_info):
        super().__init__(parent)
        self.update_info = update_info
        self.user_choice = None

        self.setWindowTitle("Update Available")
        self.setFixedWidth(500)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>🎉 PrimeBooks Update Available</h2>")
        title.setStyleSheet("color: #2c3e50;")
        layout.addWidget(title)

        # Version info
        current_version = CURRENT_VERSION
        new_version = self.update_info.get('latest_version', 'Unknown')

        version_label = QLabel(
            f"<b>Current Version:</b> {current_version}<br>"
            f"<b>New Version:</b> {new_version}"
        )
        layout.addWidget(version_label)

        # Release notes
        release_notes = self.update_info.get('release_notes', 'Bug fixes and improvements')

        notes_label = QLabel(f"<b>What's New:</b>")
        layout.addWidget(notes_label)

        notes_text = QLabel(release_notes)
        notes_text.setWordWrap(True)
        notes_text.setStyleSheet("padding: 10px; background: #ecf0f1; border-radius: 4px;")
        layout.addWidget(notes_text)

        # File size
        file_size = self.update_info.get('file_size_mb', 'Unknown')
        size_label = QLabel(f"<b>Download Size:</b> {file_size} MB")
        layout.addWidget(size_label)

        # Update Now button
        update_btn = QPushButton("Update Now")
        update_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        update_btn.clicked.connect(self.update_now)
        layout.addWidget(update_btn)

        # Remind Later button
        later_btn = QPushButton("Remind Me Later")
        later_btn.clicked.connect(self.remind_later)
        layout.addWidget(later_btn)

        self.setLayout(layout)

    def update_now(self):
        """User chose to update now"""
        self.user_choice = 'now'
        self.accept()

    def remind_later(self):
        """User chose to be reminded later"""
        self.user_choice = 'later'
        self.reject()


class UpdateProgressDialog(QDialog):
    """Shows download and installation progress"""

    def __init__(self, parent, download_url, auth_token):
        super().__init__(parent)
        self.download_url = download_url
        self.auth_token = auth_token
        self.update_file_path = None

        self.setWindowTitle("Downloading Update")
        self.setFixedSize(400, 150)
        self.setModal(True)

        self.setup_ui()

        # Start download after dialog is shown
        QTimer.singleShot(100, self.start_download)

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h3>Downloading Update...</h3>")
        layout.addWidget(title)

        # Status label
        self.status_label = QLabel("Preparing download...")
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
        self.details_label.setStyleSheet("color: #7f8c8d; margin-top: 10px;")
        layout.addWidget(self.details_label)

        self.setLayout(layout)

    def start_download(self):
        """Start update download"""
        self.downloader = UpdateDownloader(self.download_url, self.auth_token)
        self.downloader.progress.connect(self.update_progress)
        self.downloader.download_complete.connect(self.on_download_complete)
        self.downloader.download_failed.connect(self.on_download_failed)
        self.downloader.start()

    def update_progress(self, percentage):
        """Update progress bar"""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(f"Downloading... {percentage}%")

    def on_download_complete(self, file_path):
        """Download completed"""
        self.update_file_path = file_path
        self.status_label.setText("✅ Download complete!")
        self.progress_bar.setValue(100)

        QTimer.singleShot(500, self.accept)

    def on_download_failed(self, error):
        """Download failed"""
        QMessageBox.critical(
            self,
            "Download Failed",
            f"Failed to download update:\n{error}\n\nPlease try again later."
        )
        self.reject()


# ============================================================================
# UPDATE MANAGER (Main Controller)
# ============================================================================

class UpdateManager:
    """Main update manager"""

    def __init__(self, main_window, server_url, auth_token):
        self.main_window = main_window
        self.server_url = server_url
        self.auth_token = auth_token

        # Check for updates on startup (after 2 minutes)
        QTimer.singleShot(120000, self.check_for_updates)

        # Check daily
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_for_updates)
        self.check_timer.start(86400000)  # 24 hours

        logger.info("✅ Update manager initialized")

    def check_for_updates(self, silent=True):
        """
        Check for updates
        silent=True: Don't show "No updates" message
        """
        logger.info("🔍 Checking for updates...")

        self.checker = UpdateChecker(self.server_url, self.auth_token)
        self.checker.update_available.connect(self.on_update_available)

        if not silent:
            self.checker.no_updates.connect(self.on_no_updates)

        self.checker.start()

    def on_update_available(self, update_info):
        """Handle update available"""
        logger.info(f"Update available: {update_info}")

        # Show update dialog
        dialog = UpdateAvailableDialog(self.main_window, update_info)

        if dialog.exec() and dialog.user_choice == 'now':
            self.download_and_install_update(update_info)
        else:
            logger.info("User chose to be reminded later")

    def on_no_updates(self):
        """No updates available"""
        QMessageBox.information(
            self.main_window,
            "No Updates",
            "You're running the latest version of PrimeBooks!"
        )

    def download_and_install_update(self, update_info):
        """Download and install update"""
        download_url = update_info.get('download_url')

        if not download_url:
            QMessageBox.critical(
                self.main_window,
                "Update Error",
                "Download URL not available"
            )
            return

        # Show download progress
        progress_dialog = UpdateProgressDialog(
            self.main_window,
            download_url,
            self.auth_token
        )

        if progress_dialog.exec():
            # Download successful - install
            self.install_update(progress_dialog.update_file_path)

    def install_update(self, update_file_path):
        """Install update"""
        reply = QMessageBox.question(
            self.main_window,
            "Install Update",
            "The update is ready to install.\n\n"
            "PrimeBooks will close and the update will be installed.\n"
            "The app will restart automatically.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            logger.info(f"Installing update from {update_file_path}")

            # Run installer
            if platform.system() == 'Windows':
                subprocess.Popen([update_file_path])
            else:
                # Linux/Mac
                subprocess.Popen(['chmod', '+x', update_file_path])
                subprocess.Popen([update_file_path])

            # Quit app
            self.main_window.close()
            sys.exit(0)

    def stop(self):
        """Stop update manager"""
        self.check_timer.stop()
        logger.info("Update manager stopped")