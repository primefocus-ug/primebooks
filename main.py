#!/usr/bin/env python
"""
Prime Books Desktop Application - PostgreSQL Version
Main PyQt launcher with embedded PostgreSQL
✅ SQL Dump initialization (FAST!)
✅ Proper desktop login dialog
✅ Data sync before loading app
✅ Schema-aware tenant handling
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
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )
    print("=" * 80)
    print("🐛 DEBUG MODE ENABLED")
    print("=" * 80)


# Exception handler that shows errors in GUI
def exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception handler"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    print("\n" + "=" * 80)
    print("💥 FATAL ERROR:")
    print("=" * 80)
    print(error_msg)
    print("=" * 80)

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
        pass


sys.excepthook = exception_handler

import socket
import threading
import logging
from datetime import datetime

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
    QVBoxLayout, QLineEdit, QHBoxLayout, QProgressBar, QMenu
)
from primebooks.login_dialogs import UserSwitchDialog, InitialLoginDialog
from primebooks.update_manager import UpdateManager
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QIcon, QPageLayout
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
import time

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
# SQL SCHEMA LOADER
# ============================================================================

def load_schema_from_sql(sql_file_path, schema_name=None):
    """
    Load database schema from SQL dump file

    Args:
        sql_file_path: Path to SQL file
        schema_name: If provided, replaces 'template' with this name

    Returns:
        bool: True if successful
    """
    from django.db import connection

    logger.info(f"📄 Loading schema from: {sql_file_path}")

    try:
        # Read SQL file
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        # If schema_name provided, replace 'template' references
        if schema_name:
            logger.info(f"Replacing 'template' with '{schema_name}' in SQL")
            sql_content = sql_content.replace('CREATE SCHEMA template;', f'CREATE SCHEMA {schema_name};')
            sql_content = sql_content.replace('template.', f'{schema_name}.')
            sql_content = sql_content.replace("'template'", f"'{schema_name}'")
            sql_content = sql_content.replace('SET search_path TO template;', f'SET search_path TO {schema_name};')

        # Clean the SQL content - remove problematic commands
        lines = sql_content.split('\n')
        cleaned_lines = []

        for line in lines:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # Skip comments
            if stripped.startswith('--'):
                continue

            # Skip psql commands (backslash commands)
            if stripped.startswith('\\'):
                logger.debug(f"Skipping psql command: {stripped[:50]}...")
                continue

            # Skip SET statements (session-specific)
            if stripped.upper().startswith('SET '):
                continue

            # Skip SELECT pg_catalog.set_config
            if 'pg_catalog.set_config' in stripped:
                continue

            cleaned_lines.append(line)

        cleaned_sql = '\n'.join(cleaned_lines)

        # Execute SQL statement by statement
        with connection.cursor() as cursor:
            logger.info("Executing SQL statements...")

            # Split by semicolon (statement separator)
            statements = []
            current_statement = []

            for line in cleaned_sql.split('\n'):
                current_statement.append(line)
                if line.strip().endswith(';'):
                    statements.append('\n'.join(current_statement))
                    current_statement = []

            # Execute each statement
            executed = 0
            skipped = 0

            for statement in statements:
                statement = statement.strip()
                if not statement:
                    continue

                try:
                    cursor.execute(statement)
                    executed += 1
                except Exception as e:
                    # Log but continue with other statements
                    logger.warning(f"Skipped statement (error: {str(e)[:50]}): {statement[:100]}...")
                    skipped += 1

            logger.info(f"✅ Executed {executed} statements ({skipped} skipped)")

        logger.info(f"✅ Schema loaded from {sql_file_path}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to load schema from SQL: {e}", exc_info=True)
        return False


def verify_schema_tables(schema_name, required_tables=None):
    """
    Verify that required tables exist in schema

    Args:
        schema_name: Schema to check
        required_tables: List of table names to verify (None = skip check)

    Returns:
        bool: True if all tables exist
    """
    from django.db import connection

    if not required_tables:
        # Just check that schema exists
        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT schema_name
                           FROM information_schema.schemata
                           WHERE schema_name = %s;
                           """, [schema_name])

            result = cursor.fetchone()
            if result:
                logger.info(f"✅ Schema '{schema_name}' exists")
                return True
            else:
                logger.error(f"❌ Schema '{schema_name}' does not exist")
                return False

    # Check specific tables
    with connection.cursor() as cursor:
        cursor.execute(f"SET search_path TO {schema_name};")

        missing_tables = []
        for table in required_tables:
            cursor.execute("""
                           SELECT EXISTS (SELECT
                                          FROM information_schema.tables
                                          WHERE table_schema = %s
                                            AND table_name = %s);
                           """, [schema_name, table])

            if not cursor.fetchone()[0]:
                missing_tables.append(table)

        if missing_tables:
            logger.error(f"❌ Missing tables in '{schema_name}': {missing_tables}")
            return False

        logger.info(f"✅ All required tables exist in '{schema_name}'")
        return True


# ============================================================================
# DESKTOP LOGIN DIALOG
# ============================================================================

class DesktopLoginDialog(QDialog):
    """Desktop login dialog - Native Qt window"""

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
        self.subdomain_input.setPlaceholderText("e.g. test   (if url is test.primebooks.sale)")
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
        self.email_input.setPlaceholderText("nashvybzesdeveloper@gmail.com")
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

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def handle_login(self):
        """Handle login button click"""
        subdomain = self.subdomain_input.text().strip()
        email = self.email_input.text().strip()
        password = self.password_input.text()

        if not subdomain:
            self.show_error("Please enter your company subdomain")
            return

        if not email:
            self.show_error("Please enter your email")
            return

        if not password:
            self.show_error("Please enter your password")
            return

        self.login_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("Authenticating...")
        self.status_label.setStyleSheet("color: #3498db;")

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

            auth_manager = DesktopAuthManager()

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
        QTimer.singleShot(100, self.start_sync)

    def setup_ui(self):
        layout = QVBoxLayout()

        title = QLabel("<h2>📥 Downloading Your Data</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.status_label = QLabel("Preparing to download...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; margin: 10px 0;")
        layout.addWidget(self.status_label)

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

            sync_manager = SyncManager(
                tenant_id=self.tenant_id,
                schema_name=self.subdomain,
                auth_token=self.token
            )

            self.progress_update.emit("Checking for existing data...", 20)
            is_first_sync = check_sync_needed(
                tenant_id=self.tenant_id,
                schema_name=self.subdomain
            )

            self.progress_update.emit("Starting data download...", 25)

            def progress_callback(message, percentage):
                self.progress_update.emit(message, percentage)

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

            if not pg_manager.setup(progress_callback=self.progress.emit):
                self.finished.emit(False, "Failed to setup PostgreSQL")
                return

            settings.DATABASES['default'].update(pg_manager.get_connection_params())

            self.finished.emit(True, "PostgreSQL ready")

        except Exception as e:
            logger.error(f"PostgreSQL init error: {e}", exc_info=True)
            self.finished.emit(False, str(e))


def initialize_django(data_dir):
    """
    ✅ NEW: Initialize Django using SQL dumps (FAST!)
    """
    logger.info("Initializing Django in desktop mode")
    logger.info(f"Data directory: {data_dir}")

    # Setup Django first
    import django
    django.setup()
    logger.info("✅ Django apps loaded")

    # Check if this is first run
    first_run = not (data_dir / '.initialized').exists()

    if first_run:
        logger.info("🚀 First run detected - loading schema from SQL dumps...")

        try:
            from django.db import connection

            # ============================================================
            # STEP 1: Load public schema from SQL dump
            # ============================================================
            logger.info("📄 Loading public schema from primebooks_public.sql...")

            public_sql_path = BASE_DIR / 'primebooks_public.sql'
            if not public_sql_path.exists():
                raise FileNotFoundError(f"Public schema SQL file not found: {public_sql_path}")

            if not load_schema_from_sql(public_sql_path):
                raise Exception("Failed to load public schema from SQL")

            logger.info("✅ Public schema loaded from SQL (2-3 seconds instead of 60!)")

            # ✅ Ensure django_session table exists in public schema
            logger.info("🔄 Creating django_session table in public schema...")
            try:
                from django.core.management import call_command
                from django.db import connection

                with connection.cursor() as cursor:
                    cursor.execute("SET search_path TO public;")

                    # Create django_session table if it doesn't exist
                    cursor.execute("""
                                   CREATE TABLE IF NOT EXISTS django_session
                                   (
                                       session_key
                                       varchar
                                   (
                                       40
                                   ) NOT NULL PRIMARY KEY,
                                       session_data text NOT NULL,
                                       expire_date timestamp with time zone NOT NULL
                                                                 );
                                   """)

                    cursor.execute("""
                                   CREATE INDEX IF NOT EXISTS django_session_expire_date_idx
                                       ON django_session (expire_date);
                                   """)

                logger.info("✅ django_session table ready in public schema")
            except Exception as e:
                logger.warning(f"⚠️ Could not create session table: {e}")

            # ============================================================
            # STEP 2: Verify public schema
            # ============================================================
            if not verify_schema_tables('public'):
                raise Exception("Public schema verification failed")

            # Mark as initialized
            (data_dir / '.initialized').touch()
            logger.info("✅ Database initialized successfully using SQL dumps! 🚀")

        except Exception as e:
            logger.error(f"❌ Failed to initialize from SQL dumps: {e}", exc_info=True)
            logger.warning("⚠️ Falling back to Django migrations...")

            # Fallback to old method
            try:
                from django.core.management import call_command

                # Create basic tables manually
                with connection.cursor() as cursor:
                    cursor.execute("CREATE SCHEMA IF NOT EXISTS public;")
                    cursor.execute("SET search_path TO public;")

                # Run migrations
                call_command('migrate_schemas',
                             schema_name='public',
                             interactive=False,
                             verbosity=2)

                (data_dir / '.initialized').touch()
                logger.info("✅ Database initialized using migrations (fallback)")

            except Exception as fallback_error:
                logger.error(f"❌ Fallback migration also failed: {fallback_error}", exc_info=True)
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
# MAIN WINDOW (Keeping your existing implementation)
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
        self.update_manager = None

        self.setup_ui()
        self.setup_toolbar()
        self.setup_statusbar()
        self.setup_sync_scheduler()
        self.setup_print_support()
        self.setup_update_manager()

    def setup_ui(self):
        """Setup the main window UI"""
        self.setWindowTitle(f"PrimeBooks Desktop - {self.subdomain}")
        self.setGeometry(100, 100, 1400, 900)

        self.browser = QWebEngineView()

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

        QTimer.singleShot(1000, self.load_application)

    def setup_print_support(self):
        """Setup print functionality for web pages"""
        self.browser.page().printRequested.connect(self.handle_print_request)
        logger.info("✅ Print support enabled (JavaScript window.print() intercept)")

    def setup_update_manager(self):
        """Initialize auto-update manager"""
        try:
            server_url = f"http://{self.subdomain}.localhost:8000" if settings.DEBUG else f"https://{self.subdomain}.primebooks.sale"

            self.update_manager = UpdateManager(
                main_window=self,
                server_url=server_url,
                auth_token=self.auth_token
            )
            logger.info("✅ Update manager started")
        except Exception as e:
            logger.error(f"Failed to start update manager: {e}")

    # ========================================================================
    # ✅ NEW: USER SWITCHING
    # ========================================================================

    def switch_user(self):
        """Switch to different user without restarting app"""
        logger.info("🔄 User switch requested")

        try:
            # Show user switch dialog
            dialog = UserSwitchDialog(
                company_schema=self.subdomain,
                company_id=self.tenant_id,
                parent=self
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                # User successfully authenticated
                new_user_email = dialog.user_data['email']

                logger.info(f"✅ User switched: {self.current_user_email} → {new_user_email}")

                self.current_user_email = new_user_email

                # Update status bar
                self.status_label.setText(f"● {self.subdomain} - {new_user_email}")

                # Reload the page to show new user's session
                self.browser.reload()

                # Show success message
                self.statusBar.showMessage(f"✅ Logged in as {new_user_email}", 3000)
            else:
                logger.info("User switch cancelled")

        except Exception as e:
            logger.error(f"User switch error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Switch User Error",
                f"Failed to switch user:\n\n{str(e)}"
            )

    def handle_print_request(self):
        """Handle print request from JavaScript (window.print())"""
        logger.info("🖨️ Print requested from web page (window.print() called)")
        self.print_to_pdf_simple()

    def print_page(self):
        """Main print function - shows user choice"""
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
                self.print_to_pdf_simple()
            else:
                self.print_direct_new_api()

        except Exception as e:
            logger.error(f"Print error: {e}", exc_info=True)
            self.print_to_pdf_simple()

    def print_direct_new_api(self):
        """Direct printing using PyQt6 new API"""
        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
            from PyQt6.QtGui import QPageLayout, QPageSize

            logger.info("🖨️ Attempting direct print with new API...")

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)

            page_layout = QPageLayout()
            page_layout.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            page_layout.setOrientation(QPageLayout.Orientation.Portrait)
            printer.setPageLayout(page_layout)

            dialog = QPrintDialog(printer, self)
            dialog.setWindowTitle("Print Document")

            if dialog.exec() == QPrintDialog.DialogCode.Accepted:
                logger.info("Print dialog accepted, rendering page...")
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
        logger.info(f"Received PDF data: {len(data)} bytes")

    def print_to_pdf_simple(self):
        """Export to PDF and open"""
        try:
            import tempfile
            import time
            from PyQt6.QtCore import QTimer

            logger.info("📄 Starting PDF export...")

            timestamp = int(time.time())
            pdf_filename = f"primebooks_print_{timestamp}.pdf"
            pdf_path = Path(tempfile.gettempdir()) / pdf_filename

            logger.info(f"PDF will be saved to: {pdf_path}")

            self.browser.page().printToPdf(str(pdf_path))

            QTimer.singleShot(1500, lambda: self.open_pdf_for_print(pdf_path))

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
            QTimer.singleShot(2000, lambda: self.open_pdf_for_print(pdf_path))
            return

        try:
            logger.info(f"✅ Opening PDF: {pdf_path}")

            if platform.system() == 'Windows':
                os.startfile(str(pdf_path))
            elif platform.system() == 'Darwin':
                subprocess.run(['open', str(pdf_path)])
            else:
                subprocess.run(['xdg-open', str(pdf_path)])

            logger.info(f"✅ PDF opened successfully")

            self.statusBar.showMessage(
                f"✅ PDF ready! Location: {pdf_path.name}",
                5000
            )

        except Exception as e:
            logger.error(f"Failed to open PDF: {e}", exc_info=True)

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
        """Setup application toolbar with navigation, sync, and user switching"""
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

        # Print
        print_action = QAction("🖨️ Print to PDF", self)
        print_action.setShortcut("Ctrl+P")
        print_action.triggered.connect(self.print_to_pdf_simple)
        toolbar.addAction(print_action)

        toolbar.addSeparator()

        # Manual Sync
        sync_action = QAction("🔄 Sync Data", self)
        sync_action.triggered.connect(self.manual_sync)
        toolbar.addAction(sync_action)

        toolbar.addSeparator()

        # ✅ NEW: Switch User Button
        switch_user_action = QAction("👥 Switch User", self)
        switch_user_action.triggered.connect(self.switch_user)
        toolbar.addAction(switch_user_action)

        toolbar.addSeparator()

        # Status label (show current user)
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

            from primebooks.sync_dialogs import ManualSyncDialog
            from PyQt6.QtWidgets import QMessageBox

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

            dialog = ManualSyncDialog(
                parent=self,
                tenant_id=self.tenant_id,
                schema_name=self.subdomain,
                auth_token=self.auth_token
            )

            result = dialog.exec()

            if result == QDialog.DialogCode.Accepted:
                logger.info("✅ Manual sync completed")
                self.browser.reload()
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

    def logout(self):
        """Logout with option to switch user or quit"""
        # Create custom message box
        msg = QMessageBox(self)
        msg.setWindowTitle("Logout")
        msg.setText("What would you like to do?")
        msg.setIcon(QMessageBox.Icon.Question)

        # Add buttons
        switch_btn = msg.addButton("Switch User", QMessageBox.ButtonRole.AcceptRole)
        quit_btn = msg.addButton("Quit App", QMessageBox.ButtonRole.RejectRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.ActionRole)

        msg.exec()

        clicked_button = msg.clickedButton()

        if clicked_button == switch_btn:
            # Switch user
            self.switch_user()

        elif clicked_button == quit_btn:
            # Quit app
            reply = QMessageBox.question(
                self,
                'Quit',
                'Are you sure you want to quit PrimeBooks?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                # Stop services
                if self.sync_scheduler:
                    self.sync_scheduler.stop()
                if self.update_manager:
                    self.update_manager.stop()

                # Stop PostgreSQL
                try:
                    from primebooks.postgres_manager import EmbeddedPostgresManager
                    from django.conf import settings
                    pg_manager = EmbeddedPostgresManager(settings.DESKTOP_DATA_DIR)
                    pg_manager.stop()
                except:
                    pass

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
            # Stop services
            if self.sync_scheduler:
                self.sync_scheduler.stop()
            if self.update_manager:  # ✅ NEW
                self.update_manager.stop()

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


def main():
    """Main application entry point"""
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

        # PostgreSQL Init
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

            # Authentication
            from primebooks.auth import DesktopAuthManager
            auth_manager = DesktopAuthManager()

            saved_token, saved_user, saved_company = auth_manager.load_credentials()
            token, company_data, subdomain, tenant_id = None, None, None, None

            if not saved_token or not saved_company:
                logger.info("No saved credentials found. Opening login...")
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

                logger.info(f"Performing initial sync for {subdomain}...")

                # ✅ Create tenant schema from SQL BEFORE syncing data
                logger.info("📄 Creating tenant schema from SQL dump...")
                tenant_sql_path = BASE_DIR / 'primebooks_tenant.sql'

                if not tenant_sql_path.exists():
                    logger.warning(f"⚠️ Tenant SQL not found: {tenant_sql_path}")
                    logger.warning("⚠️ Tenant will be created during data sync")
                else:
                    if load_schema_from_sql(tenant_sql_path, schema_name=subdomain):
                        logger.info(f"✅ Tenant schema '{subdomain}' created from SQL!")
                    else:
                        logger.warning("⚠️ Failed to load tenant schema from SQL")

                sync_dialog = DataSyncDialog(subdomain, token, company_data)
                sync_dialog.exec()
            else:
                logger.info("Using saved credentials...")
                token = saved_token
                company_data = saved_company
                user_data = saved_user

                subdomain = company_data.get('schema_name') or company_data.get('subdomain')
                tenant_id = company_data.get('company_id')

                if not subdomain or not tenant_id:
                    logger.info("Invalid saved credentials. Showing login...")
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

                    sync_dialog = DataSyncDialog(subdomain, token, company_data)
                    sync_dialog.exec()

            refs['subdomain'] = subdomain
            refs['tenant_id'] = tenant_id
            refs['token'] = token

            # Start Django server and wait for it
            port = find_free_port()
            refs['port'] = port

            logger.info(f"Starting Django server on port {port}...")

            django_thread = threading.Thread(
                target=run_django_server,
                args=(port,),
                daemon=True
            )
            django_thread.start()

            # Wait for server
            import socket
            import time

            max_wait = 30
            start_time = time.time()
            server_ready = False

            progress_dialog = QProgressDialog("Starting server...", None, 0, 0)
            progress_dialog.setWindowTitle("PrimeBooks - Starting Server")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.show()

            logger.info(f"⏳ Waiting for server to start on port {port}...")

            while time.time() - start_time < max_wait:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex(('127.0.0.1', port))
                    sock.close()

                    if result == 0:
                        logger.info(f"✅ Server is ready on port {port}")
                        server_ready = True
                        break
                except:
                    pass

                elapsed = int(time.time() - start_time)
                progress_dialog.setLabelText(f"Starting server... ({elapsed}s)")
                app.processEvents()
                time.sleep(0.5)

            progress_dialog.close()

            if not server_ready:
                logger.error("❌ Server failed to start within 30 seconds")
                QMessageBox.critical(
                    None,
                    "Server Error",
                    "Django server failed to start. Please check the logs."
                )
                app.quit()
                return

            logger.info("⏳ Waiting for routes to register...")
            time.sleep(2)

            logger.info("✅ Django server ready!")

            # Show main window
            refs['window'] = PrimeBooksWindow(
                port=port,
                subdomain=subdomain,
                tenant_id=tenant_id,
                auth_token=token
            )
            refs['window'].show()

            logger.info("✅ Application ready!")

        postgres_thread = PostgresInitThread()
        postgres_thread.progress.connect(on_postgres_progress)
        postgres_thread.finished.connect(on_postgres_finished)
        postgres_thread.start()

        sys.exit(app.exec())

    except Exception as e:
        logger.error(f"Fatal error in main(): {e}", exc_info=True)

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