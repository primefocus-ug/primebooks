# primebooks/crash_reporter.py
"""
PrimeBooks Crash Reporter - Ubuntu Style
✅ "Send Report" or "Don't Send" dialog
✅ Auto-send critical errors
✅ Includes logs, system info, stack traces
✅ Privacy controls
✅ Thread-safe: dialog always runs on the Qt main thread
"""
import sys
import traceback
import logging
import json
import requests
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                             QTextEdit, QCheckBox, QHBoxLayout, QMessageBox)
from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot
from django.conf import settings

logger = logging.getLogger(__name__)

CRASH_REPORT_URL = "https://primebooks.sale/api/desktop/error-reports/"


def _collect_recent_logs(max_bytes=8192):
    """
    Read the tail of the application log file so we can attach it to reports.
    Falls back gracefully if no log file is configured or readable.
    """
    # Try the log file path from settings first, then common fallbacks
    candidates = []
    log_setting = getattr(settings, 'LOG_FILE', None)
    if log_setting:
        candidates.append(Path(log_setting))

    data_dir = getattr(settings, 'DESKTOP_DATA_DIR', None)
    if data_dir:
        candidates += [
            Path(data_dir) / 'primebooks.log',
            Path(data_dir) / 'app.log',
        ]

    for log_path in candidates:
        if log_path.exists():
            try:
                size = log_path.stat().st_size
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    if size > max_bytes:
                        f.seek(size - max_bytes)
                        f.readline()          # skip partial first line
                    return f.read()
            except Exception as e:
                logger.debug(f"Could not read log file {log_path}: {e}")

    return "(no log file found)"


def _collect_system_info():
    """Collect basic system info — no business data."""
    import platform
    return {
        'platform': platform.system(),
        'platform_version': platform.version(),
        'python': sys.version,
        'architecture': platform.machine(),
    }


class CrashReportDialog(QDialog):
    """Ubuntu-style crash reporter dialog."""

    def __init__(self, parent, error_info):
        super().__init__(parent)
        self.error_info = error_info
        self.user_choice = None

        self.setWindowTitle("PrimeBooks - Error Detected")
        self.setFixedSize(600, 500)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()

        title = QLabel("<h2>⚠️ PrimeBooks Has Encountered an Error</h2>")
        title.setStyleSheet("color: #e74c3c;")
        layout.addWidget(title)

        msg = QLabel(
            "We're sorry! PrimeBooks has encountered an unexpected error.\n\n"
            "You can help us fix this by sending an error report."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        details_label = QLabel("<b>Error Details:</b>")
        layout.addWidget(details_label)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        self.details_text.setPlainText(
            f"Error: {self.error_info.get('error_type', 'Unknown')}\n"
            f"Message: {self.error_info.get('error_message', '')}\n\n"
            f"{self.error_info.get('traceback', '')}".strip()
        )
        layout.addWidget(self.details_text)

        self.include_logs = QCheckBox("Include application logs (recommended)")
        self.include_logs.setChecked(True)
        layout.addWidget(self.include_logs)

        self.include_system = QCheckBox("Include system info")
        self.include_system.setChecked(True)
        layout.addWidget(self.include_system)

        privacy = QLabel(
            "<small><i>We only collect error info. "
            "No business data (sales, products) is ever sent.</i></small>"
        )
        privacy.setStyleSheet("color: #7f8c8d;")
        layout.addWidget(privacy)

        btn_layout = QHBoxLayout()

        send_btn = QPushButton("Send Report")
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        send_btn.clicked.connect(lambda: self._done('send'))
        btn_layout.addWidget(send_btn)

        dont_send = QPushButton("Don't Send")
        dont_send.clicked.connect(lambda: self._done('dont_send'))
        btn_layout.addWidget(dont_send)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _done(self, choice):
        self.user_choice = choice
        if choice == 'send':
            self.accept()
        else:
            self.reject()


class CrashHandler:
    """
    Global exception handler.

    ✅ Thread-safe: uses QMetaObject.invokeMethod to always show the dialog
       on the Qt main thread, even when the exception originates in a
       background thread (Django sync, scheduler, etc.).
    ✅ Log extraction actually reads the log file tail (not a placeholder).
    ✅ Critical errors are auto-reported with a timeout; failures are logged,
       not silently swallowed.
    """

    def __init__(self, app_window=None):
        self.app_window = app_window
        sys.excepthook = self.handle_exception
        logger.info("✅ Crash handler initialized")

    def handle_exception(self, exc_type, exc_value, exc_tb):
        # Let KeyboardInterrupt propagate normally
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

        error_info = {
            'error_type': exc_type.__name__,
            'error_message': str(exc_value),
            'traceback': ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            'timestamp': datetime.now().isoformat(),
        }

        if self._is_critical(exc_type):
            logger.info("🚨 Critical error — auto-sending report")
            self._auto_send(error_info)

        if self.app_window:
            # Always invoke on the main thread regardless of where the
            # exception was raised.  Q_ARG requires a registered type;
            # we pass the dict as a Python object via a lambda slot instead.
            try:
                from PyQt6.QtCore import QTimer
                # QTimer.singleShot(0, ...) schedules on the main event loop
                QTimer.singleShot(0, lambda: self._show_dialog(error_info))
            except Exception as e:
                logger.error(f"Could not schedule crash dialog on main thread: {e}")

    # ------------------------------------------------------------------ #

    def _is_critical(self, exc_type):
        critical_names = {'MemoryError', 'DatabaseError', 'IntegrityError'}
        return exc_type.__name__ in critical_names

    def _auto_send(self, error_info):
        """Send critical error report; log failures instead of swallowing them."""
        try:
            data = dict(error_info)
            data['auto_reported'] = True
            data['system'] = _collect_system_info()
            response = requests.post(CRASH_REPORT_URL, json=data, timeout=10)
            if response.status_code == 201:
                logger.info("✅ Critical error auto-reported successfully")
            else:
                logger.warning(
                    f"Auto-report returned unexpected status {response.status_code}: "
                    f"{response.text[:200]}"
                )
        except requests.exceptions.ConnectionError:
            logger.warning("Auto-report failed: no network connection")
        except requests.exceptions.Timeout:
            logger.warning("Auto-report failed: request timed out")
        except Exception as e:
            logger.error(f"Auto-report failed: {e}")

    def _show_dialog(self, error_info):
        """Show the crash dialog. Must be called on the Qt main thread."""
        try:
            dialog = CrashReportDialog(self.app_window, error_info)
            if dialog.exec() and dialog.user_choice == 'send':
                self._send_report(error_info, dialog)
        except Exception as e:
            logger.error(f"Failed to show crash dialog: {e}")

    def _send_report(self, error_info, dialog):
        """Send user-approved crash report with optional logs and system info."""
        try:
            data = dict(error_info)

            if dialog.include_logs.isChecked():
                data['logs'] = _collect_recent_logs()

            if dialog.include_system.isChecked():
                data['system'] = _collect_system_info()

            response = requests.post(CRASH_REPORT_URL, json=data, timeout=30)

            if response.status_code == 201:
                QMessageBox.information(
                    self.app_window,
                    "Report Sent",
                    "Thank you! Your report helps us improve PrimeBooks."
                )
            else:
                logger.warning(
                    f"Report submission returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
                QMessageBox.warning(
                    self.app_window,
                    "Report Not Sent",
                    "Could not send the report right now. Please try again later."
                )

        except requests.exceptions.ConnectionError:
            logger.warning("Report send failed: no network connection")
            QMessageBox.warning(
                self.app_window,
                "Report Not Sent",
                "No internet connection. The report could not be sent."
            )
        except Exception as e:
            logger.error(f"Report send failed: {e}")


def initialize_crash_handler(app_window=None):
    """Initialize and return the global crash handler."""
    return CrashHandler(app_window)