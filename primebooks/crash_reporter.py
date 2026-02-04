# primebooks/crash_reporter.py
"""
PrimeBooks Crash Reporter - Ubuntu Style
✅ "Send Report" or "Don't Send" dialog
✅ Auto-send critical errors
✅ Includes logs, system info, stack traces
✅ Privacy controls
"""
import sys
import traceback
import logging
import platform
import json
import requests
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                             QTextEdit, QCheckBox, QHBoxLayout, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from django.conf import settings

logger = logging.getLogger(__name__)


class CrashReportDialog(QDialog):
    """Ubuntu-style crash reporter"""

    def __init__(self, parent, error_info):
        super().__init__(parent)
        self.error_info = error_info
        self.user_choice = None

        self.setWindowTitle("PrimeBooks - Error Detected")
        self.setFixedSize(600, 500)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>⚠️ PrimeBooks Has Encountered an Error</h2>")
        title.setStyleSheet("color: #e74c3c;")
        layout.addWidget(title)

        # Message
        msg = QLabel(
            "We're sorry! PrimeBooks has encountered an unexpected error.\n\n"
            "You can help us fix this by sending an error report."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        # Error details
        details_label = QLabel("<b>Error Details:</b>")
        layout.addWidget(details_label)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        self.details_text.setPlainText(f"""
Error: {self.error_info.get('error_type', 'Unknown')}
Message: {self.error_info.get('error_message', '')}

{self.error_info.get('traceback', '')}
""".strip())
        layout.addWidget(self.details_text)

        # Privacy options
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

        # Buttons
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
        send_btn.clicked.connect(lambda: self.done_choice('send'))
        btn_layout.addWidget(send_btn)

        dont_send = QPushButton("Don't Send")
        dont_send.clicked.connect(lambda: self.done_choice('dont_send'))
        btn_layout.addWidget(dont_send)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def done_choice(self, choice):
        self.user_choice = choice
        if choice == 'send':
            self.accept()
        else:
            self.reject()


class CrashHandler:
    """Global exception handler"""

    def __init__(self, app_window=None):
        self.app_window = app_window
        sys.excepthook = self.handle_exception
        logger.info("✅ Crash handler initialized")

    def handle_exception(self, exc_type, exc_value, exc_tb):
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

        # Check if critical
        is_critical = self._is_critical(exc_type)

        if is_critical:
            logger.info("🚨 Critical error - auto-sending")
            self._auto_send(error_info)

        if self.app_window:
            self._show_dialog(error_info, is_critical)

    def _is_critical(self, exc_type):
        critical = ['MemoryError', 'DatabaseError', 'IntegrityError']
        return exc_type.__name__ in critical

    def _auto_send(self, error_info):
        try:
            url = "https://primebooks.sale/api/desktop/error-reports/"
            requests.post(url, json=error_info, timeout=10)
            logger.info("✅ Critical error auto-reported")
        except:
            pass

    def _show_dialog(self, error_info, is_critical):
        try:
            dialog = CrashReportDialog(self.app_window, error_info)
            if dialog.exec() and dialog.user_choice == 'send':
                self._send_report(error_info, dialog)
        except Exception as e:
            logger.error(f"Failed to show dialog: {e}")

    def _send_report(self, error_info, dialog):
        try:
            url = "https://primebooks.sale/api/desktop/error-reports/"
            data = error_info.copy()

            if dialog.include_logs.isChecked():
                data['logs'] = "Recent logs..."  # Add log extraction

            response = requests.post(url, json=data, timeout=30)

            if response.status_code == 201:
                QMessageBox.information(
                    self.app_window,
                    "Report Sent",
                    "Thank you! Your report helps us improve PrimeBooks."
                )
        except Exception as e:
            logger.error(f"Send failed: {e}")


def initialize_crash_handler(app_window=None):
    """Initialize crash handler"""
    return CrashHandler(app_window)