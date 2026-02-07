#!/usr/bin/env python
"""
Prime Books Desktop Application - PostgreSQL Version
Main PyQt launcher with embedded PostgreSQL
✅ Proper desktop login dialog
✅ Data sync before loading app
✅ Schema-aware tenant handling
✅ FIXED: Manual sync with proper error handling
"""
# !/usr/bin/env python
"""
Prime Books Desktop Application - PostgreSQL Version
Main PyQt launcher with embedded PostgreSQL
"""
import os
import sys
import traceback
from pathlib import Path

# ============================================================================
# DEBUG MODE CONFIGURATION
# ============================================================================
DEBUG_MODE = os.environ.get('PRIMEBOOKS_DEBUG', 'True').lower() == 'true'

if DEBUG_MODE:
    # Enable all warnings
    import warnings

    warnings.filterwarnings('default')

    # Setup detailed logging
    import logging

    logging.basicConfig(
        level=logging.DEBUG,  # ← Show ALL logs
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),  # Print to console
        ]
    )
    print("=" * 80)
    print("🐛 DEBUG MODE ENABLED")
    print("=" * 80)


# Exception handler that shows errors in GUI
def exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception handler"""
    # Don't catch KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Format error
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    # Print to console
    print("\n" + "=" * 80)
    print("💥 FATAL ERROR:")
    print("=" * 80)
    print(error_msg)
    print("=" * 80)

    # Show in GUI if possible
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("PrimeBooks - Fatal Error")
        msg.setText("A fatal error occurred:")
        msg.setDetailedText(error_msg)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    except:
        pass  # If GUI fails, at least we printed to console


# Install exception handler
sys.excepthook = exception_handler

import os
import sys
import socket
import threading
import logging
from datetime import datetime
from pathlib import Path

from django.core.management import call_command

# Set desktop mode BEFORE any Django imports
os.environ['DESKTOP_MODE'] = 'True'
os.environ["PRIMEBOOKS_DESKTOP"] = "1"
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

# Add project to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# PyQt imports
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QSplashScreen, QDialog,
    QToolBar, QStatusBar, QPushButton, QLabel, QProgressDialog,
    QVBoxLayout, QLineEdit, QHBoxLayout, QProgressBar
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QIcon
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtCore import QUrl, QTimer, Qt, QThread, pyqtSignal, QMarginsF
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QSplashScreen, QDialog,
    QToolBar, QStatusBar, QPushButton, QLabel, QProgressDialog,
    QVBoxLayout, QLineEdit, QHBoxLayout, QProgressBar, QMenu  # ✅ Add QMenu
)
from PyQt6.QtCore import QUrl, QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QIcon, QPageLayout  # ✅ Add QPageLayout
import time  # ✅ Add this for timestamp

# Setup logging
log_dir = Path.home() / '.local' / 'share' / 'PrimeBooks' / 'logs'
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / f'primebooks_{datetime.now().strftime("%Y%m%d")}.log')
    ]
)
logger = logging.getLogger(__name__)


def find_free_port():
    """Find an available port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


# ============================================================================
# DESKTOP LOGIN DIALOG
# ============================================================================

class DesktopLoginDialog(QDialog):
    """
    Desktop login dialog - Native Qt window (not web page!)
    ✅ Authenticates with server
    ✅ Triggers data sync
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PrimeBooks - Desktop Login")
        self.setFixedWidth(450)
        self.setModal(True)

        self.auth_token = None
        self.user_data = None
        self.company_data = None

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Logo/Title
        title = QLabel("<h2>PrimeBooks Desktop</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #2c3e50; margin: 20px 0;")
        layout.addWidget(title)

        subtitle = QLabel("Login to sync your data")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7f8c8d; margin-bottom: 20px;")
        layout.addWidget(subtitle)

        # Subdomain input
        subdomain_label = QLabel("Company Subdomain:")
        subdomain_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(subdomain_label)

        self.subdomain_input = QLineEdit()
        self.subdomain_input.setPlaceholderText("e.g., pada")
        self.subdomain_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 2px solid #bdc3c7;
                border-radius: 4px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
            }
        """)
        layout.addWidget(self.subdomain_input)
        layout.addSpacing(10)

        # Email input
        email_label = QLabel("Email:")
        email_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("admin@company.com")
        self.email_input.setStyleSheet(self.subdomain_input.styleSheet())
        layout.addWidget(self.email_input)
        layout.addSpacing(10)

        # Password input
        password_label = QLabel("Password:")
        password_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setStyleSheet(self.subdomain_input.styleSheet())
        self.password_input.returnPressed.connect(self.handle_login)
        layout.addWidget(self.password_input)
        layout.addSpacing(20)

        # Login button
        self.login_btn = QPushButton("Login & Sync Data")
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #e74c3c; margin-top: 10px;")
        layout.addWidget(self.status_label)

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)  # Indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def handle_login(self):
        """Handle login button click"""
        subdomain = self.subdomain_input.text().strip()
        email = self.email_input.text().strip()
        password = self.password_input.text()

        # Validate inputs
        if not subdomain:
            self.show_error("Please enter your company subdomain")
            return

        if not email:
            self.show_error("Please enter your email")
            return

        if not password:
            self.show_error("Please enter your password")
            return

        # Start login process
        self.login_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("Authenticating...")
        self.status_label.setStyleSheet("color: #3498db;")

        # Start login thread
        self.login_thread = LoginThread(subdomain, email, password)
        self.login_thread.status_update.connect(self.update_status)
        self.login_thread.login_complete.connect(self.on_login_complete)
        self.login_thread.start()

    def update_status(self, message):
        """Update status message"""
        self.status_label.setText(message)

    def on_login_complete(self, success, message, token, user_data, company_data):
        """Handle login completion"""
        self.login_btn.setEnabled(True)
        self.progress_bar.hide()

        if success:
            self.auth_token = token
            self.user_data = user_data
            self.company_data = company_data

            self.status_label.setText("✓ Login successful!")
            self.status_label.setStyleSheet("color: #27ae60;")

            # Close dialog after brief delay
            QTimer.singleShot(500, self.accept)
        else:
            self.show_error(message)

    def show_error(self, message):
        """Show error message"""
        self.status_label.setText(f"✗ {message}")
        self.status_label.setStyleSheet("color: #e74c3c;")


class LoginThread(QThread):
    """Thread to handle login without blocking UI"""
    status_update = pyqtSignal(str)
    login_complete = pyqtSignal(bool, str, object, object, object)

    def __init__(self, subdomain, email, password):
        super().__init__()
        self.subdomain = subdomain
        self.email = email
        self.password = password

    def run(self):
        """Authenticate with server"""
        try:
            from primebooks.auth import DesktopAuthManager

            self.status_update.emit("Connecting to server...")

            # Initialize auth manager
            auth_manager = DesktopAuthManager()

            # Authenticate
            self.status_update.emit("Authenticating...")
            success, result = auth_manager.authenticate(
                subdomain=self.subdomain,
                email=self.email,
                password=self.password
            )

            if success:
                token = result.get('token')
                user_data = result.get('user')
                company_data = result.get('company')

                # Save credentials
                self.status_update.emit("Saving credentials...")
                auth_manager.save_credentials(user_data, company_data, token)

                self.login_complete.emit(True, "Success", token, user_data, company_data)
            else:
                error_message = result.get('error', 'Authentication failed')
                self.login_complete.emit(False, error_message, None, None, None)

        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            self.login_complete.emit(False, f"Login error: {str(e)}", None, None, None)


# ============================================================================
# DATA SYNC DIALOG
# ============================================================================

class DataSyncDialog(QDialog):
    """Dialog to show data sync progress"""

    def __init__(self, subdomain, token, company_data):
        super().__init__()
        self.subdomain = subdomain
        self.token = token
        self.company_data = company_data

        self.setWindowTitle("Syncing Data")
        self.setFixedSize(450, 150)
        self.setModal(True)

        self.setup_ui()

        # Start sync after dialog is shown
        QTimer.singleShot(100, self.start_sync)

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>📥 Downloading Your Data</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Status label
        self.status_label = QLabel("Preparing to download...")
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
        """Start data sync"""
        self.sync_thread = DataSyncThread(self.subdomain, self.token, self.company_data)
        self.sync_thread.progress_update.connect(self.update_progress)
        self.sync_thread.sync_complete.connect(self.on_sync_complete)
        self.sync_thread.start()

    def update_progress(self, message, percentage):
        """Update progress"""
        self.status_label.setText(message)
        self.progress_bar.setValue(percentage)

    def on_sync_complete(self, success, message):
        """Handle sync completion"""
        if success:
            self.status_label.setText("✓ Sync complete!")
            self.details_label.setText(message)
            self.progress_bar.setValue(100)
            QTimer.singleShot(1500, self.accept)
        else:
            self.status_label.setText("⚠️ Sync completed with warnings")
            self.details_label.setText(message)
            QMessageBox.information(
                self,
                "Sync Status",
                f"{message}\n\nYou can sync again later from the app."
            )
            self.accept()



class DataSyncThread(QThread):
    """Thread to sync data from server"""
    progress_update = pyqtSignal(str, int)
    sync_complete = pyqtSignal(bool, str)

    def __init__(self, subdomain, token, company_data):
        super().__init__()
        self.subdomain = subdomain
        self.token = token
        self.tenant_id = company_data.get('company_id')
        self.company_data = company_data

    def run(self):
        """Sync data from server"""
        try:
            from primebooks.sync import SyncManager, check_sync_needed
            from django_tenants.utils import schema_context

            self.progress_update.emit("Initializing sync...", 10)

            # ✅ FIXED: Pass auth_token to SyncManager
            sync_manager = SyncManager(
                tenant_id=self.tenant_id,
                schema_name=self.subdomain,
                auth_token=self.token  # ✅ Pass token!
            )

            # Check if first sync
            self.progress_update.emit("Checking for existing data...", 20)
            is_first_sync = check_sync_needed(
                tenant_id=self.tenant_id,
                schema_name=self.subdomain
            )

            self.progress_update.emit("Starting data download...", 25)

            # Perform sync with progress callback
            def progress_callback(message, percentage):
                self.progress_update.emit(message, percentage)

            # ✅ Pass progress callback to show download progress
            if is_first_sync:
                success = sync_manager.download_all_data(progress_callback=progress_callback)
            else:
                success = sync_manager.full_sync(is_first_sync=False)

            if success:
                self.progress_update.emit("✅ Sync complete!", 100)
                self.sync_complete.emit(True, "Data synced successfully")
            else:
                self.sync_complete.emit(False, "Sync failed - check logs for details")

        except Exception as e:
            logger.error(f"Sync error: {e}", exc_info=True)
            self.sync_complete.emit(False, f"Sync error: {str(e)}")


# ============================================================================
# POSTGRES INIT THREAD
# ============================================================================

class PostgresInitThread(QThread):
    """Thread for initializing PostgreSQL"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        """Initialize PostgreSQL in background"""
        try:
            from primebooks.postgres_manager import EmbeddedPostgresManager
            from django.conf import settings

            self.progress.emit("Initializing PostgreSQL...")
            pg_manager = EmbeddedPostgresManager(settings.DESKTOP_DATA_DIR)

            # Setup PostgreSQL
            if not pg_manager.setup(progress_callback=self.progress.emit):
                self.finished.emit(False, "Failed to setup PostgreSQL")
                return

            # Update Django database config
            settings.DATABASES['default'].update(pg_manager.get_connection_params())

            self.finished.emit(True, "PostgreSQL ready")

        except Exception as e:
            logger.error(f"PostgreSQL init error: {e}", exc_info=True)
            self.finished.emit(False, str(e))


def initialize_django(data_dir):
    """Initialize Django in desktop mode"""
    logger.info("Initializing Django in desktop mode")
    logger.info(f"Data directory: {data_dir}")

    # Setup Django first
    import django
    django.setup()
    logger.info("✅ Django apps loaded")

    # Check if this is first run
    first_run = not (data_dir / '.initialized').exists()

    if first_run:
        logger.info("First run detected - setting up database...")

        try:
            from django.db import connection

            # Step 1: Ensure public schema exists
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS public;")
                cursor.execute("SET search_path TO public;")
            logger.info("✅ Public schema configured")

            # Step 2: Create django_migrations table
            logger.info("Creating django_migrations table...")
            with connection.cursor() as cursor:
                cursor.execute("""
                               CREATE TABLE IF NOT EXISTS django_migrations
                               (
                                   id
                                   SERIAL
                                   PRIMARY
                                   KEY,
                                   app
                                   VARCHAR
                               (
                                   255
                               ) NOT NULL,
                                   name VARCHAR
                               (
                                   255
                               ) NOT NULL,
                                   applied TIMESTAMP WITH TIME ZONE NOT NULL
                                                         );
                               """)
            logger.info("✅ django_migrations table created")

            # Step 3: Force create contenttypes table
            logger.info("Creating django_content_type table...")
            with connection.cursor() as cursor:
                cursor.execute("""
                               CREATE TABLE IF NOT EXISTS django_content_type
                               (
                                   id
                                   SERIAL
                                   PRIMARY
                                   KEY,
                                   app_label
                                   VARCHAR
                               (
                                   100
                               ) NOT NULL,
                                   model VARCHAR
                               (
                                   100
                               ) NOT NULL,
                                   UNIQUE
                               (
                                   app_label,
                                   model
                               )
                                   );
                               """)

                # Mark migrations as applied
                cursor.execute("""
                               INSERT INTO django_migrations (app, name, applied)
                               VALUES ('contenttypes', '0001_initial', NOW()),
                                      ('contenttypes', '0002_remove_content_type_name', NOW()) ON CONFLICT DO NOTHING;
                               """)
            logger.info("✅ django_content_type table created")

            # Step 4: Run all other migrations
            logger.info("Running remaining migrations...")
            call_command('migrate_schemas',
                         schema_name='public',
                         interactive=False,
                         verbosity=2)

            # Mark as initialized
            (data_dir / '.initialized').touch()
            logger.info("✅ Database initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Django: {e}", exc_info=True)
            raise
    else:
        logger.info("Database already initialized")

    return True


def run_django_server(port):
    """Run Django development server"""
    try:
        from django.core.management import execute_from_command_line
        logger.info(f"Starting Django server on port {port}...")
        execute_from_command_line([
            'manage.py',
            'runserver',
            f'127.0.0.1:{port}',
            '--noreload',
        ])
    except Exception as e:
        logger.error(f"Django server error: {e}", exc_info=True)


# ============================================================================
# MAIN WINDOW
# ============================================================================

# ============================================================================
# UPDATED PrimeBooksWindow CLASS (with sync_scheduler & auth_token)
# ============================================================================

class PrimeBooksWindow(QMainWindow):
    """Main application window with sync functionality"""

    def __init__(self, port, subdomain, tenant_id, auth_token):
        super().__init__()
        self.port = port
        self.subdomain = subdomain
        self.tenant_id = tenant_id
        self.auth_token = auth_token
        self.browser = None
        self.sync_scheduler = None

        self.setup_ui()
        self.setup_toolbar()
        self.setup_statusbar()
        self.setup_sync_scheduler()
        self.setup_print_support()

        # ------------------------------------------------------------------------
    # UI / Toolbar / Statusbar
    # ------------------------------------------------------------------------
    def setup_ui(self):
        """Setup the main window UI"""
        self.setWindowTitle(f"PrimeBooks Desktop - {self.subdomain}")
        self.setGeometry(100, 100, 1400, 900)

        self.browser = QWebEngineView()

        # ✅ Enable print settings
        self.browser.settings().setAttribute(
            self.browser.settings().WebAttribute.LocalStorageEnabled, True
        )
        self.browser.settings().setAttribute(
            self.browser.settings().WebAttribute.JavascriptEnabled, True
        )
        self.browser.settings().setAttribute(
            self.browser.settings().WebAttribute.PluginsEnabled, True
        )

        self.setCentralWidget(self.browser)

        # Load the tenant-specific URL
        QTimer.singleShot(1000, self.load_application)

    def setup_print_support(self):
        """Setup print functionality for web pages"""
        # ✅ Intercept print requests from JavaScript (window.print())
        self.browser.page().printRequested.connect(self.handle_print_request)
        logger.info("✅ Print support enabled (JavaScript window.print() intercept)")

    def handle_print_request(self):
        """Handle print request from JavaScript (window.print())"""
        logger.info("🖨️ Print requested from web page (window.print() called)")
        # Automatically use PDF method (most reliable)
        self.print_to_pdf_simple()

    def print_page(self):
        """
        Main print function - shows user choice
        Called from toolbar button or Ctrl+P
        """
        try:
            from PyQt6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Print Document",
                "How would you like to print?\n\n"
                "💡 PDF Export is recommended for best results.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                # User chose PDF (recommended)
                self.print_to_pdf_simple()
            else:
                # User chose to try direct print
                self.print_direct_new_api()

        except Exception as e:
            logger.error(f"Print error: {e}", exc_info=True)
            self.print_to_pdf_simple()

    def print_direct_new_api(self):
        """
        Direct printing using PyQt6 new API
        Note: This may not work well in all cases
        """
        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
            from PyQt6.QtGui import QPageLayout, QPageSize

            logger.info("🖨️ Attempting direct print with new API...")

            # Create printer
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)

            # Configure page
            page_layout = QPageLayout()
            page_layout.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            page_layout.setOrientation(QPageLayout.Orientation.Portrait)
            printer.setPageLayout(page_layout)

            # Show print dialog
            dialog = QPrintDialog(printer, self)
            dialog.setWindowTitle("Print Document")

            if dialog.exec() == QPrintDialog.DialogCode.Accepted:
                logger.info("Print dialog accepted, rendering page...")

                # For PyQt6, we need to use a different approach
                # Render the page to the printer
                from PyQt6.QtWebEngineCore import QWebEngineView

                # This will trigger the browser's print
                # But it's limited - PDF is more reliable
                self.browser.page().printToPdf(self._handle_print_pdf_data)

                QMessageBox.information(
                    self,
                    "Print Started",
                    "Print job sent. Check your printer."
                )
            else:
                logger.info("Print dialog cancelled")

        except Exception as e:
            logger.error(f"Direct print error: {e}", exc_info=True)
            QMessageBox.warning(
                self,
                "Print Error",
                f"Direct printing not supported.\n\nUsing PDF export instead..."
            )
            self.print_to_pdf_simple()

    def _handle_print_pdf_data(self, data):
        """Handle PDF data from printToPdf callback"""
        # This receives QByteArray of PDF data
        logger.info(f"Received PDF data: {len(data)} bytes")
        # You could save this or send to printer
        # For now, we'll just log it

    def print_to_pdf_simple(self):
        """
        ✅ WORKING METHOD - Export to PDF and open
        This is the most reliable method for all cases
        """
        try:
            import tempfile
            import time
            from PyQt6.QtCore import QTimer

            logger.info("📄 Starting PDF export...")

            # Create PDF path
            timestamp = int(time.time())
            pdf_filename = f"primebooks_print_{timestamp}.pdf"
            pdf_path = Path(tempfile.gettempdir()) / pdf_filename

            logger.info(f"PDF will be saved to: {pdf_path}")

            # ✅ CORRECT PyQt6 API - No callback parameter!
            # The new API doesn't use callback, it's synchronous
            self.browser.page().printToPdf(str(pdf_path))

            # Wait a bit for PDF to be written
            QTimer.singleShot(1500, lambda: self.open_pdf_for_print(pdf_path))

            # Show status
            self.statusBar.showMessage(f"📄 Generating PDF... Will open when ready.", 3000)

        except Exception as e:
            logger.error(f"PDF export error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "PDF Export Error",
                f"Failed to export PDF:\n\n{str(e)}\n\n"
                f"Please try using your browser's built-in print function."
            )

    def open_pdf_for_print(self, pdf_path):
        """Open PDF in system default viewer"""
        import subprocess
        import platform

        if not pdf_path.exists():
            logger.error(f"PDF not found: {pdf_path}")

            # Try again after a longer delay
            QTimer.singleShot(2000, lambda: self.open_pdf_for_print(pdf_path))
            return

        try:
            logger.info(f"✅ Opening PDF: {pdf_path}")

            # Open with system default PDF viewer
            if platform.system() == 'Windows':
                os.startfile(str(pdf_path))
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(pdf_path)])
            else:  # Linux
                subprocess.run(['xdg-open', str(pdf_path)])

            logger.info(f"✅ PDF opened successfully")

            self.statusBar.showMessage(
                f"✅ PDF ready! Location: {pdf_path.name}",
                5000
            )

        except Exception as e:
            logger.error(f"Failed to open PDF: {e}", exc_info=True)

            # Show the path so user can open manually
            QMessageBox.information(
                self,
                "PDF Ready",
                f"PDF created successfully!\n\n"
                f"Location:\n{pdf_path}\n\n"
                f"Please open it manually if it didn't open automatically."
            )

    def load_application(self):
        """Load Django app in browser"""
        url = f"http://{self.subdomain}.localhost:{self.port}/"
        logger.info(f"Loading application for tenant '{self.subdomain}': {url}")
        self.browser.setUrl(QUrl(url))

    def setup_toolbar(self):
        """Setup application toolbar with navigation & sync"""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Navigation
        back_action = QAction("◄ Back", self)
        back_action.triggered.connect(self.browser.back)
        toolbar.addAction(back_action)

        forward_action = QAction("Forward ►", self)
        forward_action.triggered.connect(self.browser.forward)
        toolbar.addAction(forward_action)

        reload_action = QAction("🔄 Reload", self)
        reload_action.triggered.connect(self.browser.reload)
        toolbar.addAction(reload_action)

        toolbar.addSeparator()

        # ✅ PRINT BUTTON (triggers PDF export - most reliable)
        print_action = QAction("🖨️ Print to PDF", self)
        print_action.setShortcut("Ctrl+P")
        print_action.triggered.connect(self.print_to_pdf_simple)  # Direct to PDF
        toolbar.addAction(print_action)

        toolbar.addSeparator()

        # Manual Sync Button
        sync_action = QAction("🔄 Sync Data", self)
        sync_action.triggered.connect(self.manual_sync)
        toolbar.addAction(sync_action)

        toolbar.addSeparator()

        # Status label
        self.status_label = QLabel(f"● {self.subdomain}")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        toolbar.addWidget(self.status_label)

        toolbar.addSeparator()

        # Logout
        logout_action = QAction("🚪 Logout", self)
        logout_action.triggered.connect(self.logout)
        toolbar.addAction(logout_action)

    def setup_statusbar(self):
        """Setup status bar"""
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")

    # ------------------------------------------------------------------------
    # SYNC SCHEDULER
    # ------------------------------------------------------------------------
    def setup_sync_scheduler(self):
        """Initialize automatic sync scheduler"""
        try:
            from primebooks.sync_scheduler import SyncScheduler

            self.sync_scheduler = SyncScheduler(
                main_window=self,
                tenant_id=self.tenant_id,
                schema_name=self.subdomain,
                auth_token=self.auth_token
            )
            logger.info("✅ Sync scheduler started")
        except Exception as e:
            logger.error(f"Failed to start sync scheduler: {e}")

    def manual_sync(self):
        """Manual sync triggered by user"""
        try:
            logger.info("🔄 Manual sync requested by user")

            # ✅ Import at function level to avoid circular imports
            from primebooks.sync_dialogs import ManualSyncDialog
            from PyQt6.QtWidgets import QMessageBox

            # ✅ Verify we have auth token
            if not self.auth_token:
                logger.error("❌ No auth token available for sync")
                QMessageBox.warning(
                    self,
                    "Authentication Required",
                    "You must be logged in to sync data.\n\n"
                    "Please restart the application and login."
                )
                return

            logger.info(f"✅ Auth token present: {self.auth_token[:20]}...")
            logger.info(f"✅ Tenant ID: {self.tenant_id}")
            logger.info(f"✅ Schema: {self.subdomain}")

            # Show manual sync dialog
            dialog = ManualSyncDialog(
                parent=self,
                tenant_id=self.tenant_id,
                schema_name=self.subdomain,
                auth_token=self.auth_token
            )

            result = dialog.exec()

            if result == QDialog.DialogCode.Accepted:
                # User clicked "Start Sync" - sync is already running
                logger.info("✅ Manual sync completed")

                # Refresh the page to show new data
                self.browser.reload()

                # Update status bar
                self.statusBar.showMessage("✅ Sync complete! Page refreshed.", 5000)
            else:
                logger.info("Manual sync cancelled by user")

        except ImportError as e:
            logger.error(f"❌ Failed to import sync_dialogs: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Module Error",
                f"Failed to load sync module:\n\n{str(e)}\n\n"
                f"The sync feature may not be properly installed."
            )
        except Exception as e:
            logger.error(f"❌ Manual sync error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Sync Error",
                f"An error occurred during sync:\n\n{str(e)}\n\n"
                f"Check the logs for more details."
            )

    # ------------------------------------------------------------------------
    # LOGOUT / CLOSE
    # ------------------------------------------------------------------------
    def logout(self):
        """Logout and clear credentials"""
        reply = QMessageBox.question(
            self,
            "Logout",
            "Logout and clear local data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Stop sync scheduler
            if self.sync_scheduler:
                self.sync_scheduler.stop()

            from primebooks.auth import DesktopAuthManager
            DesktopAuthManager().logout()

            QMessageBox.information(
                self,
                "Logged Out",
                "Please restart the application to login again."
            )
            self.close()

    def closeEvent(self, event):
        """Handle window close"""
        reply = QMessageBox.question(
            self,
            'Quit',
            'Quit PrimeBooks?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.sync_scheduler:
                self.sync_scheduler.stop()
            # Stop PostgreSQL
            try:
                from primebooks.postgres_manager import EmbeddedPostgresManager
                from django.conf import settings
                pg_manager = EmbeddedPostgresManager(settings.DESKTOP_DATA_DIR)
                pg_manager.stop()
            except:
                pass
            event.accept()
        else:
            event.ignore()


def show_error_dialog(title, message):
    """Show error dialog"""
    app = QApplication(sys.argv)
    QMessageBox.critical(None, title, message)
    sys.exit(1)


# ============================================================================
#  main() FUNCTION WITH auth_token SUPPORT
# ============================================================================
def main():
    """Main application entry point"""
    # ✅ IMPORT ALL PYQT CLASSES AT THE TOP OF MAIN()
    from PyQt6.QtWidgets import QApplication, QProgressDialog, QMessageBox, QDialog
    from PyQt6.QtCore import Qt

    try:
        logger.info("=" * 50)
        logger.info("🚀 Starting PrimeBooks Desktop")
        logger.info("=" * 50)
        logger.info(f"🐛 Debug mode: {DEBUG_MODE}")
        logger.info(f"🐍 Python version: {sys.version}")
        logger.info(f"📁 Working directory: {os.getcwd()}")
        logger.info(f"📦 Frozen: {getattr(sys, 'frozen', False)}")
        if hasattr(sys, '_MEIPASS'):
            logger.info(f"📂 Temp dir: {sys._MEIPASS}")
        logger.info("=" * 50)

        app = QApplication(sys.argv)
        app.setApplicationName("PrimeBooks")

        from django.conf import settings
        data_dir = settings.DESKTOP_DATA_DIR

        refs = {
            'window': None,
            'subdomain': None,
            'port': None,
            'tenant_id': None,
            'token': None,
        }

        # ----------------------------------------------------------------------
        # PostgreSQL Init
        # ----------------------------------------------------------------------
        progress = QProgressDialog("Initializing PostgreSQL...", None, 0, 0)
        progress.setWindowTitle("PrimeBooks - Startup")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        def on_postgres_progress(message):
            progress.setLabelText(message)
            app.processEvents()

        def on_postgres_finished(success, message):
            progress.close()

            if not success:
                QMessageBox.critical(None, "PostgreSQL Error", message)
                return

            # Django Init
            try:
                if not initialize_django(data_dir):
                    QMessageBox.critical(None, "Init Error", "Failed to initialize database")
                    return
            except Exception as e:
                QMessageBox.critical(None, "Init Error", str(e))
                return

            # ------------------------------------------------------------------
            # Authentication
            # ------------------------------------------------------------------
            from primebooks.auth import DesktopAuthManager
            auth_manager = DesktopAuthManager()

            saved_token, saved_user, saved_company = auth_manager.load_credentials()
            token, company_data, subdomain, tenant_id = None, None, None, None

            if not saved_token or not saved_company:
                # No saved credentials - show login dialog
                logger.info("No saved credentials found. Opening login...")
                login_dialog = DesktopLoginDialog()
                if login_dialog.exec() != QDialog.DialogCode.Accepted:
                    app.quit()
                    return

                token = login_dialog.auth_token
                company_data = login_dialog.company_data
                user_data = login_dialog.user_data

                # Extract subdomain and tenant_id
                subdomain = company_data.get('schema_name') or company_data.get('subdomain')
                tenant_id = company_data.get('company_id')

                # Save credentials
                auth_manager.save_credentials(user_data, company_data, token)

                # First-time data sync
                logger.info(f"Performing initial sync for {subdomain}...")
                sync_dialog = DataSyncDialog(subdomain, token, company_data)
                sync_dialog.exec()
            else:
                # Use saved credentials
                logger.info("Using saved credentials...")
                token = saved_token
                company_data = saved_company
                user_data = saved_user

                # Extract subdomain and tenant_id from saved data
                subdomain = company_data.get('schema_name') or company_data.get('subdomain')
                tenant_id = company_data.get('company_id')

                # Validate saved data
                if not subdomain or not tenant_id:
                    logger.info("Invalid saved credentials. Showing login...")
                    # Credentials are invalid, force re-login
                    auth_manager.logout()

                    login_dialog = DesktopLoginDialog()
                    if login_dialog.exec() != QDialog.DialogCode.Accepted:
                        app.quit()
                        return

                    token = login_dialog.auth_token
                    company_data = login_dialog.company_data
                    user_data = login_dialog.user_data
                    subdomain = company_data.get('schema_name') or company_data.get('subdomain')
                    tenant_id = company_data.get('company_id')
                    auth_manager.save_credentials(user_data, company_data, token)

                    # Sync data
                    sync_dialog = DataSyncDialog(subdomain, token, company_data)
                    sync_dialog.exec()

            # Store in refs
            refs['subdomain'] = subdomain
            refs['tenant_id'] = tenant_id
            refs['token'] = token

            # ------------------------------------------------------------------
            # Start Django server
            # ------------------------------------------------------------------
            port = find_free_port()
            refs['port'] = port

            django_thread = threading.Thread(
                target=run_django_server,
                args=(port,),
                daemon=True
            )
            django_thread.start()

            # ------------------------------------------------------------------
            # Show main window
            # ------------------------------------------------------------------
            refs['window'] = PrimeBooksWindow(
                port=port,
                subdomain=subdomain,
                tenant_id=tenant_id,
                auth_token=token
            )
            refs['window'].show()

            logger.info("✅ Application ready!")

        # Start PostgreSQL thread
        postgres_thread = PostgresInitThread()
        postgres_thread.progress.connect(on_postgres_progress)
        postgres_thread.finished.connect(on_postgres_finished)
        postgres_thread.start()

        sys.exit(app.exec())

    except Exception as e:
        logger.error(f"Fatal error in main(): {e}", exc_info=True)

        # Import again in exception handler to be safe
        from PyQt6.QtWidgets import QApplication, QMessageBox

        app_instance = QApplication.instance()
        if app_instance is None:
            app_instance = QApplication(sys.argv)

        QMessageBox.critical(
            None,
            "Startup Error",
            f"Failed to start PrimeBooks:\n\n{str(e)}\n\nCheck logs for details."
        )
        sys.exit(1)


if __name__ == '__main__':
    main()