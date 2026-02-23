#!/usr/bin/env python
"""
Prime Books Desktop Application - PostgreSQL Version
Main PyQt launcher with embedded PostgreSQL
✅ SQL Dump initialization (FAST!)
✅ Proper desktop login dialog
✅ Data sync before loading app
✅ Schema-aware tenant handling
"""
import sys
import io

# Force UTF-8 for stdout/stderr — prevents charmap codec crashes on Windows
# when emoji characters appear in log output during frozen/compiled mode
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Also set environment variable for subprocesses
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

if hasattr(sys.stdout, 'buffer'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
import sys
import traceback
from pathlib import Path

# ============================================================================
# DEBUG MODE CONFIGURATION
# ============================================================================
DEBUG_MODE = os.environ.get('PRIMEBOOKS_DEBUG', 'False').lower() == 'true'

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
else:
    # ✅ PRODUCTION MODE: Redirect all output to log files
    import logging
    from pathlib import Path
    from datetime import datetime

    # Create log directory
    log_dir = Path.home() / '.local' / 'share' / 'PrimeBooks' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)

    # Setup file-only logging (no console output)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / f'primebooks_{datetime.now().strftime("%Y%m%d")}.log')
        ]
    )

    # Redirect stdout and stderr to log file (suppress all console output)
    sys.stdout = open(log_dir / f'stdout_{datetime.now().strftime("%Y%m%d")}.log', 'a')
    sys.stderr = open(log_dir / f'stderr_{datetime.now().strftime("%Y%m%d")}.log', 'a')


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
    QVBoxLayout, QLineEdit, QHBoxLayout, QProgressBar, QMenu,QFrame,QWidget
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QFrame, QWidget, QScrollArea, QSizePolicy
)
from PyQt6.QtGui import QIcon, QFont, QPalette, QColor, QResizeEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtWebEngineCore import QWebEnginePage
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


def find_icon():
    """Find icon file at runtime — works both frozen (Nuitka) and unfrozen."""
    if getattr(sys, 'frozen', False):
        # Nuitka: icon sits next to the compiled binary
        base = Path(sys.argv[0]).parent
    else:
        base = Path(__file__).resolve().parent

    for name in ['icon.png', 'icon.ico', 'icon.icns']:
        candidate = base / name
        if candidate.exists():
            return str(candidate)
    return None


# ============================================================================
# SQL SCHEMA LOADER
# ============================================================================



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

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QFrame, QWidget, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QPixmap, QPainter, QIcon, QColor
import logging
import os
from enum import Enum
from dataclasses import dataclass
from typing import Optional



class Theme(Enum):
    """Available themes"""
    LIGHT = "light"
    DARK = "dark"
    NORD = "nord"
    DRACULA = "dracula"
    SOLARIZED_LIGHT = "solarized_light"
    SOLARIZED_DARK = "solarized_dark"
    MONOKAI = "monokai"
    OCEAN = "ocean"
    FOREST = "forest"
    SUNSET = "sunset"


@dataclass
class ThemeColors:
    """Theme color scheme"""
    # Background colors
    bg_primary: str
    bg_secondary: str
    bg_input: str
    bg_input_focus: str

    # Text colors
    text_primary: str
    text_secondary: str
    text_placeholder: str
    text_on_primary: str

    # Border colors
    border_default: str
    border_focus: str

    # Accent colors
    accent_primary: str
    accent_secondary: str
    accent_hover: str

    # Status colors
    success_bg: str
    success_text: str
    error_bg: str
    error_text: str

    # Progress colors
    progress_bg: str
    progress_active: str
    progress_complete: str
    progress_error: str

    # Header gradient (if None, uses solid accent_primary)
    header_gradient_start: Optional[str] = None
    header_gradient_end: Optional[str] = None


class ThemeManager:
    """Manages theme configurations"""

    THEMES = {
        Theme.LIGHT: ThemeColors(
            bg_primary="#ffffff",
            bg_secondary="#f8f9fa",
            bg_input="#f7fafc",
            bg_input_focus="#ffffff",
            text_primary="#2d3748",
            text_secondary="#718096",
            text_placeholder="#a0aec0",
            text_on_primary="#ffffff",
            border_default="#e2e8f0",
            border_focus="#667eea",
            accent_primary="#667eea",
            accent_secondary="#764ba2",
            accent_hover="#5568d3",
            success_bg="#f0fff4",
            success_text="#2f855a",
            error_bg="#fff5f5",
            error_text="#c53030",
            progress_bg="#f7fafc",
            progress_active="#ebf4ff",
            progress_complete="#f0fff4",
            progress_error="#fff5f5",
            header_gradient_start="#667eea",
            header_gradient_end="#764ba2",
        ),

        Theme.DARK: ThemeColors(
            bg_primary="#1a202c",
            bg_secondary="#2d3748",
            bg_input="#2d3748",
            bg_input_focus="#374151",
            text_primary="#f7fafc",
            text_secondary="#cbd5e0",
            text_placeholder="#718096",
            text_on_primary="#ffffff",
            border_default="#4a5568",
            border_focus="#667eea",
            accent_primary="#667eea",
            accent_secondary="#764ba2",
            accent_hover="#7c3aed",
            success_bg="#065f46",
            success_text="#d1fae5",
            error_bg="#7f1d1d",
            error_text="#fecaca",
            progress_bg="#374151",
            progress_active="#1e3a8a",
            progress_complete="#065f46",
            progress_error="#7f1d1d",
            header_gradient_start="#667eea",
            header_gradient_end="#764ba2",
        ),

        Theme.NORD: ThemeColors(
            bg_primary="#2e3440",
            bg_secondary="#3b4252",
            bg_input="#3b4252",
            bg_input_focus="#434c5e",
            text_primary="#eceff4",
            text_secondary="#d8dee9",
            text_placeholder="#616e88",
            text_on_primary="#eceff4",
            border_default="#4c566a",
            border_focus="#88c0d0",
            accent_primary="#88c0d0",
            accent_secondary="#81a1c1",
            accent_hover="#5e81ac",
            success_bg="#a3be8c",
            success_text="#2e3440",
            error_bg="#bf616a",
            error_text="#eceff4",
            progress_bg="#434c5e",
            progress_active="#5e81ac",
            progress_complete="#a3be8c",
            progress_error="#bf616a",
            header_gradient_start="#5e81ac",
            header_gradient_end="#81a1c1",
        ),

        Theme.DRACULA: ThemeColors(
            bg_primary="#282a36",
            bg_secondary="#44475a",
            bg_input="#44475a",
            bg_input_focus="#6272a4",
            text_primary="#f8f8f2",
            text_secondary="#f8f8f2",
            text_placeholder="#6272a4",
            text_on_primary="#f8f8f2",
            border_default="#6272a4",
            border_focus="#bd93f9",
            accent_primary="#bd93f9",
            accent_secondary="#ff79c6",
            accent_hover="#9580ff",
            success_bg="#50fa7b",
            success_text="#282a36",
            error_bg="#ff5555",
            error_text="#f8f8f2",
            progress_bg="#44475a",
            progress_active="#6272a4",
            progress_complete="#50fa7b",
            progress_error="#ff5555",
            header_gradient_start="#bd93f9",
            header_gradient_end="#ff79c6",
        ),

        Theme.SOLARIZED_LIGHT: ThemeColors(
            bg_primary="#fdf6e3",
            bg_secondary="#eee8d5",
            bg_input="#eee8d5",
            bg_input_focus="#93a1a1",
            text_primary="#657b83",
            text_secondary="#839496",
            text_placeholder="#93a1a1",
            text_on_primary="#fdf6e3",
            border_default="#93a1a1",
            border_focus="#268bd2",
            accent_primary="#268bd2",
            accent_secondary="#2aa198",
            accent_hover="#073642",
            success_bg="#859900",
            success_text="#fdf6e3",
            error_bg="#dc322f",
            error_text="#fdf6e3",
            progress_bg="#eee8d5",
            progress_active="#268bd2",
            progress_complete="#859900",
            progress_error="#dc322f",
            header_gradient_start="#268bd2",
            header_gradient_end="#2aa198",
        ),

        Theme.SOLARIZED_DARK: ThemeColors(
            bg_primary="#002b36",
            bg_secondary="#073642",
            bg_input="#073642",
            bg_input_focus="#586e75",
            text_primary="#839496",
            text_secondary="#93a1a1",
            text_placeholder="#586e75",
            text_on_primary="#fdf6e3",
            border_default="#586e75",
            border_focus="#268bd2",
            accent_primary="#268bd2",
            accent_secondary="#2aa198",
            accent_hover="#6c71c4",
            success_bg="#859900",
            success_text="#fdf6e3",
            error_bg="#dc322f",
            error_text="#fdf6e3",
            progress_bg="#073642",
            progress_active="#268bd2",
            progress_complete="#859900",
            progress_error="#dc322f",
            header_gradient_start="#268bd2",
            header_gradient_end="#2aa198",
        ),

        Theme.MONOKAI: ThemeColors(
            bg_primary="#272822",
            bg_secondary="#3e3d32",
            bg_input="#3e3d32",
            bg_input_focus="#49483e",
            text_primary="#f8f8f2",
            text_secondary="#f8f8f2",
            text_placeholder="#75715e",
            text_on_primary="#f8f8f2",
            border_default="#75715e",
            border_focus="#66d9ef",
            accent_primary="#66d9ef",
            accent_secondary="#a6e22e",
            accent_hover="#ae81ff",
            success_bg="#a6e22e",
            success_text="#272822",
            error_bg="#f92672",
            error_text="#f8f8f2",
            progress_bg="#3e3d32",
            progress_active="#66d9ef",
            progress_complete="#a6e22e",
            progress_error="#f92672",
            header_gradient_start="#66d9ef",
            header_gradient_end="#a6e22e",
        ),

        Theme.OCEAN: ThemeColors(
            bg_primary="#0d1117",
            bg_secondary="#161b22",
            bg_input="#161b22",
            bg_input_focus="#21262d",
            text_primary="#c9d1d9",
            text_secondary="#8b949e",
            text_placeholder="#6e7681",
            text_on_primary="#ffffff",
            border_default="#30363d",
            border_focus="#58a6ff",
            accent_primary="#58a6ff",
            accent_secondary="#1f6feb",
            accent_hover="#388bfd",
            success_bg="#238636",
            success_text="#c9d1d9",
            error_bg="#da3633",
            error_text="#c9d1d9",
            progress_bg="#161b22",
            progress_active="#1f6feb",
            progress_complete="#238636",
            progress_error="#da3633",
            header_gradient_start="#1f6feb",
            header_gradient_end="#58a6ff",
        ),

        Theme.FOREST: ThemeColors(
            bg_primary="#1b2b1b",
            bg_secondary="#2d4a2d",
            bg_input="#2d4a2d",
            bg_input_focus="#3d5a3d",
            text_primary="#e8f5e8",
            text_secondary="#b8d8b8",
            text_placeholder="#7a9a7a",
            text_on_primary="#ffffff",
            border_default="#4a6a4a",
            border_focus="#6abf69",
            accent_primary="#6abf69",
            accent_secondary="#4a9d48",
            accent_hover="#8ad989",
            success_bg="#4a9d48",
            success_text="#e8f5e8",
            error_bg="#c44545",
            error_text="#e8f5e8",
            progress_bg="#2d4a2d",
            progress_active="#4a9d48",
            progress_complete="#6abf69",
            progress_error="#c44545",
            header_gradient_start="#4a9d48",
            header_gradient_end="#6abf69",
        ),

        Theme.SUNSET: ThemeColors(
            bg_primary="#2b1b2b",
            bg_secondary="#3d2d3d",
            bg_input="#3d2d3d",
            bg_input_focus="#4d3d4d",
            text_primary="#f5e8e8",
            text_secondary="#d8b8b8",
            text_placeholder="#9a7a7a",
            text_on_primary="#ffffff",
            border_default="#6a4a5a",
            border_focus="#ff6b9d",
            accent_primary="#ff6b9d",
            accent_secondary="#c44569",
            accent_hover="#ff8bb4",
            success_bg="#69c469",
            success_text="#2b1b2b",
            error_bg="#c44545",
            error_text="#f5e8e8",
            progress_bg="#3d2d3d",
            progress_active="#c44569",
            progress_complete="#69c469",
            progress_error="#c44545",
            header_gradient_start="#c44569",
            header_gradient_end="#ff6b9d",
        ),
    }

    @classmethod
    def get_theme(cls, theme: Theme) -> ThemeColors:
        """Get theme colors"""
        return cls.THEMES.get(theme, cls.THEMES[Theme.LIGHT])


class ThemedLoginDialog(QDialog):
    """Fully responsive and themeable login dialog"""

    def __init__(self, logo_path=None, theme=Theme.LIGHT, auto_detect_system_theme=False):
        """
        Initialize themed login dialog

        Args:
            logo_path (str, optional): Path to logo image file
            theme (Theme): Theme to use (default: Theme.LIGHT)
            auto_detect_system_theme (bool): Auto-detect dark/light mode from system
        """
        super().__init__()
        self.setWindowTitle("PrimeBooks Desktop - Sign In")
        self.setModal(True)

        self.logo_path = logo_path

        # Theme setup
        if auto_detect_system_theme:
            self.current_theme = self._detect_system_theme()
        else:
            self.current_theme = theme

        self.theme_colors = ThemeManager.get_theme(self.current_theme)

        # Make dialog resizable
        self.setMinimumSize(400, 550)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.resize_for_screen()

        self.auth_token = None
        self.user_data = None
        self.company_data = None

        self.setup_ui()
        self.apply_theme()

        # Set window icon
        if logo_path and os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))

    def _detect_system_theme(self) -> Theme:
        """Detect system theme (dark/light mode)"""
        try:
            from PyQt6.QtGui import QPalette
            palette = self.palette()
            window_color = palette.color(QPalette.ColorRole.Window)

            # If window background is dark, use dark theme
            if window_color.lightness() < 128:
                return Theme.DARK
            else:
                return Theme.LIGHT
        except Exception:
            return Theme.LIGHT

    def set_theme(self, theme: Theme):
        """Change theme dynamically"""
        self.current_theme = theme
        self.theme_colors = ThemeManager.get_theme(theme)
        self.apply_theme()

    def resize_for_screen(self):
        """Set appropriate size based on screen dimensions"""
        screen = self.screen().geometry()
        screen_width = screen.width()
        screen_height = screen.height()

        if screen_width < 800 or screen_height < 700:
            self.resize(min(screen_width - 40, 450), min(screen_height - 40, 600))
        elif screen_width < 1200:
            self.resize(500, 650)
        else:
            self.resize(550, 700)

    def setup_ui(self):
        # Main layout with scroll area
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Content widget
        content_widget = QWidget()
        scroll_area.setWidget(content_widget)

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Header
        self.header = self.create_header()
        content_layout.addWidget(self.header)

        # Main content area
        self.content_area = QWidget()
        self.content_area.setObjectName("contentArea")
        self.content_area_layout = QVBoxLayout(self.content_area)
        self.content_area_layout.setSpacing(0)

        self.update_content_margins()

        # Welcome section
        welcome_container = QWidget()
        welcome_layout = QVBoxLayout(welcome_container)
        welcome_layout.setContentsMargins(0, 0, 0, 0)
        welcome_layout.setSpacing(8)

        self.welcome_label = QLabel("Welcome back!")
        self.welcome_label.setObjectName("welcomeLabel")
        self.welcome_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.welcome_label.setWordWrap(True)
        welcome_layout.addWidget(self.welcome_label)

        self.subtitle = QLabel("Sign in to access your workspace")
        self.subtitle.setObjectName("subtitleLabel")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.subtitle.setWordWrap(True)
        welcome_layout.addWidget(self.subtitle)

        self.content_area_layout.addWidget(welcome_container)
        self.content_area_layout.addSpacing(20)

        # Input fields
        inputs_container = QWidget()
        inputs_layout = QVBoxLayout(inputs_container)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.setSpacing(15)

        self.subdomain_input = self.create_input_field(
            "Company Subdomain",
            "e.g., test ( if url is 'test.primebooks.sale' )",
            "🏢"
        )
        inputs_layout.addWidget(self.subdomain_input)

        self.subdomain_hint = QLabel("Enter the subdomain from your PrimeBooks URL")
        self.subdomain_hint.setObjectName("hintLabel")
        self.subdomain_hint.setWordWrap(True)
        inputs_layout.addWidget(self.subdomain_hint)
        inputs_layout.addSpacing(5)

        self.email_input = self.create_input_field(
            "Email Address",
            "nashvybzesdeveloper@gmail.com",
            "✉️"
        )
        inputs_layout.addWidget(self.email_input)
        inputs_layout.addSpacing(5)

        self.password_input = self.create_input_field(
            "Password",
            "Enter your password",
            "🔒",
            is_password=True
        )
        inputs_layout.addWidget(self.password_input)

        self.content_area_layout.addWidget(inputs_container)
        self.content_area_layout.addSpacing(20)

        # Progress section
        self.progress_section = self.create_progress_section()
        self.content_area_layout.addWidget(self.progress_section)
        self.progress_section.hide()

        # Status label
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.content_area_layout.addWidget(self.status_label)

        self.content_area_layout.addSpacing(10)

        # Login button
        self.login_btn = QPushButton("Sign In")
        self.login_btn.setObjectName("loginButton")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.login_btn.clicked.connect(self.handle_login)
        self.content_area_layout.addWidget(self.login_btn)

        # Footer
        footer_container = QWidget()
        footer_layout = QVBoxLayout(footer_container)
        footer_layout.setContentsMargins(0, 20, 0, 0)

        # Create help label
        self.help_label = QLabel("Need help? <a href='#'>Contact Support</a>")
        self.help_label.setObjectName("helpLabel")
        self.help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.help_label.setOpenExternalLinks(False)
        self.help_label.setWordWrap(True)
        footer_layout.addWidget(self.help_label)

        # WhatsApp support
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        whatsapp_number = "256785"  # Replace with your number
        default_message = "Hello PrimeBooks Desktop, I need support."
        whatsapp_url = f"https://wa.me/{whatsapp_number}?text={default_message.replace(' ', '%20')}"

        self.help_label.linkActivated.connect(
            lambda link: QDesktopServices.openUrl(QUrl(whatsapp_url))
        )

        self.content_area_layout.addWidget(footer_container)
        self.content_area_layout.addStretch()

        content_layout.addWidget(self.content_area)
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)

        self.password_input.input_field.returnPressed.connect(self.handle_login)

    def create_header(self):
        """Create header with logo"""
        header = QFrame()
        header.setObjectName("headerFrame")
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        header_content = QWidget()
        self.header_content_layout = QVBoxLayout(header_content)

        if self.logo_path and os.path.exists(self.logo_path):
            self.logo_label = QLabel()
            self.logo_label.setObjectName("logoImage")
            self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.original_pixmap = QPixmap(self.logo_path)
            self.update_logo_size()

            self.header_content_layout.addWidget(self.logo_label)

            self.tagline = QLabel("Desktop Application")
            self.tagline.setObjectName("taglineLabel")
            self.tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tagline.setWordWrap(True)
            self.header_content_layout.addWidget(self.tagline)
        else:
            self.logo_label = QLabel("📚 PrimeBooks")
            self.logo_label.setObjectName("logoLabel")
            self.logo_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.logo_label.setWordWrap(True)
            self.header_content_layout.addWidget(self.logo_label)

            self.tagline = QLabel("Desktop Application")
            self.tagline.setObjectName("taglineLabel")
            self.tagline.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.tagline.setWordWrap(True)
            self.header_content_layout.addWidget(self.tagline)

        header_layout.addWidget(header_content)
        return header

    def update_logo_size(self):
        """Update logo size"""
        if not hasattr(self, 'original_pixmap'):
            return

        width = self.width()

        if width < 450:
            logo_width = int(width * 0.5)
        elif width < 550:
            logo_width = int(width * 0.45)
        else:
            logo_width = int(width * 0.4)

        logo_width = min(logo_width, 250)

        scaled_pixmap = self.original_pixmap.scaled(
            logo_width,
            120,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.logo_label.setPixmap(scaled_pixmap)

    def create_input_field(self, label_text, placeholder, icon="", is_password=False):
        """Create input field"""
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("inputLabel")
        label.setWordWrap(True)
        layout.addWidget(label)

        input_container = QFrame()
        input_container.setObjectName("inputFrame")
        input_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_layout = QHBoxLayout(input_container)
        input_layout.setSpacing(10)

        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("iconLabel")
            input_layout.addWidget(icon_label)

        input_field = QLineEdit()
        input_field.setPlaceholderText(placeholder)
        input_field.setFrame(False)
        input_field.setObjectName("inputField")
        input_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if is_password:
            input_field.setEchoMode(QLineEdit.EchoMode.Password)

        input_layout.addWidget(input_field, 1)

        if is_password:
            toggle_btn = QPushButton("👁️")
            toggle_btn.setObjectName("togglePasswordBtn")
            toggle_btn.setFixedSize(30, 30)
            toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle_btn.clicked.connect(
                lambda: self.toggle_password_visibility(input_field, toggle_btn)
            )
            input_layout.addWidget(toggle_btn)

        layout.addWidget(input_container)
        container.input_field = input_field
        return container

    def create_progress_section(self):
        """Create progress section"""
        container = QFrame()
        container.setObjectName("progressFrame")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setSpacing(10)

        self.progress_steps = []
        steps = [
            ("Connecting", "🔌"),
            ("Authenticating", "🔐"),
            ("Syncing Data", "📥"),
            ("Finalizing", "✨")
        ]

        for step_text, emoji in steps:
            step_widget = self.create_progress_step(step_text, emoji)
            layout.addWidget(step_widget)
            self.progress_steps.append(step_widget)

        self.overall_progress = QProgressBar()
        self.overall_progress.setObjectName("overallProgress")
        self.overall_progress.setTextVisible(False)
        self.overall_progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        layout.addWidget(self.overall_progress)

        return container

    def create_progress_step(self, text, emoji):
        """Create progress step"""
        step = QFrame()
        step.setObjectName("progressStep")
        step.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(step)

        icon = QLabel(emoji)
        icon.setObjectName("stepIcon")
        layout.addWidget(icon)

        label = QLabel(text)
        label.setObjectName("stepLabel")
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(label, 1)

        status = QLabel("⏳")
        status.setObjectName("stepStatus")
        layout.addWidget(status)

        step.icon = icon
        step.label = label
        step.status = status
        step.text = text

        return step

    def resizeEvent(self, event):
        """Handle resize"""
        super().resizeEvent(event)

        width = event.size().width()

        self.update_content_margins()
        self.update_font_sizes(width)
        self.update_header_padding(width)
        self.update_button_size(width)

        if self.logo_path and os.path.exists(self.logo_path):
            self.update_logo_size()

    def update_content_margins(self):
        """Update margins"""
        width = self.width()

        if width < 450:
            margin = 20
        elif width < 550:
            margin = 30
        else:
            margin = 40

        self.content_area_layout.setContentsMargins(margin, 30, margin, 30)

    def update_font_sizes(self, width):
        """Update font sizes"""
        if width < 450:
            logo_size = 24
            welcome_size = 20
            subtitle_size = 12
        elif width < 550:
            logo_size = 28
            welcome_size = 22
            subtitle_size = 13
        else:
            logo_size = 32
            welcome_size = 24
            subtitle_size = 14

        if not (self.logo_path and os.path.exists(self.logo_path)):
            self.logo_label.setProperty("fontSize", logo_size)

        self.welcome_label.setProperty("fontSize", welcome_size)
        self.subtitle.setProperty("fontSize", subtitle_size)

        for widget in [self.logo_label, self.welcome_label, self.subtitle]:
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def update_header_padding(self, width):
        """Update header padding"""
        if width < 450:
            padding = 20
            header_height = 140 if (self.logo_path and os.path.exists(self.logo_path)) else 100
        elif width < 550:
            padding = 25
            header_height = 150 if (self.logo_path and os.path.exists(self.logo_path)) else 110
        else:
            padding = 30
            header_height = 160 if (self.logo_path and os.path.exists(self.logo_path)) else 120

        self.header_content_layout.setContentsMargins(padding, padding, padding, padding)
        self.header.setMinimumHeight(header_height)
        self.header.setMaximumHeight(header_height)

    def update_button_size(self, width):
        """Update button size"""
        if width < 450:
            button_height = 44
        elif width < 550:
            button_height = 48
        else:
            button_height = 50

        self.login_btn.setMinimumHeight(button_height)
        self.login_btn.setMaximumHeight(button_height)

    def toggle_password_visibility(self, input_field, button):
        """Toggle password visibility"""
        if input_field.echoMode() == QLineEdit.EchoMode.Password:
            input_field.setEchoMode(QLineEdit.EchoMode.Normal)
            button.setText("🙈")
        else:
            input_field.setEchoMode(QLineEdit.EchoMode.Password)
            button.setText("👁️")

    def handle_login(self):
        """Handle login"""
        subdomain = self.subdomain_input.input_field.text().strip()
        email = self.email_input.input_field.text().strip()
        password = self.password_input.input_field.text()

        self.status_label.setText("")

        if not subdomain:
            self.show_error("Please enter your company subdomain")
            return

        if not email:
            self.show_error("Please enter your email address")
            return

        if '@' not in email:
            self.show_error("Please enter a valid email address")
            return

        if not password:
            self.show_error("Please enter your password")
            return

        self.start_login_ui()

        self.login_thread = EnhancedLoginThread(subdomain, email, password)
        self.login_thread.status_update.connect(self.update_login_progress)
        self.login_thread.step_complete.connect(self.mark_step_complete)
        self.login_thread.login_complete.connect(self.on_login_complete)
        self.login_thread.start()

    def start_login_ui(self):
        """Start login UI"""
        self.login_btn.setEnabled(False)
        self.login_btn.setText("Signing in...")
        self.status_label.setText("")

        self.progress_section.show()

        for step in self.progress_steps:
            step.status.setText("⏳")
            step.setProperty("state", "pending")
            step.style().unpolish(step)
            step.style().polish(step)

        self.subdomain_input.setEnabled(False)
        self.email_input.setEnabled(False)
        self.password_input.setEnabled(False)

    def update_login_progress(self, step_index, message, progress):
        """Update progress"""
        if 0 <= step_index < len(self.progress_steps):
            step = self.progress_steps[step_index]
            step.status.setText("⏳")
            step.setProperty("state", "active")
            step.style().unpolish(step)
            step.style().polish(step)

        self.overall_progress.setValue(progress)

    def mark_step_complete(self, step_index):
        """Mark step complete"""
        if 0 <= step_index < len(self.progress_steps):
            step = self.progress_steps[step_index]
            step.status.setText("✅")
            step.setProperty("state", "complete")
            step.style().unpolish(step)
            step.style().polish(step)

    def on_login_complete(self, success, message, token, user_data, company_data):
        """Handle login complete"""
        if success:
            self.auth_token = token
            self.user_data = user_data
            self.company_data = company_data

            for i, step in enumerate(self.progress_steps):
                QTimer.singleShot(i * 100, lambda s=step: self.mark_step_complete_final(s))

            self.overall_progress.setValue(100)
            self.show_success("Login successful! Loading workspace...")

            QTimer.singleShot(1500, self.accept)
        else:
            self.reset_login_ui()
            self.show_error(message)

            for step in self.progress_steps:
                if step.property("state") == "active":
                    step.status.setText("❌")
                    step.setProperty("state", "error")
                    step.style().unpolish(step)
                    step.style().polish(step)

    def mark_step_complete_final(self, step):
        """Mark step complete final"""
        step.status.setText("✅")
        step.setProperty("state", "complete")
        step.style().unpolish(step)
        step.style().polish(step)

    def reset_login_ui(self):
        """Reset UI"""
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Sign In")
        self.progress_section.hide()

        self.subdomain_input.setEnabled(True)
        self.email_input.setEnabled(True)
        self.password_input.setEnabled(True)

    def show_error(self, message):
        """Show error"""
        self.status_label.setText(f"⚠️ {message}")
        self.status_label.setProperty("status", "error")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def show_success(self, message):
        """Show success"""
        self.status_label.setText(f"✓ {message}")
        self.status_label.setProperty("status", "success")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def apply_theme(self):
        """Apply current theme stylesheet"""
        c = self.theme_colors

        # Build header gradient or solid background
        if c.header_gradient_start and c.header_gradient_end:
            header_bg = f"""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c.header_gradient_start}, stop:1 {c.header_gradient_end});
            """
        else:
            header_bg = f"background-color: {c.accent_primary};"

        stylesheet = f"""
            QDialog {{
                background-color: {c.bg_secondary};
            }}

            #headerFrame {{
                {header_bg}
                border: none;
            }}

            #logoLabel {{
                color: {c.text_on_primary};
                font-size: 32px;
                font-weight: bold;
            }}

            #logoLabel[fontSize="24"] {{ font-size: 24px; }}
            #logoLabel[fontSize="28"] {{ font-size: 28px; }}
            #logoLabel[fontSize="32"] {{ font-size: 32px; }}

            #logoImage {{
                background: transparent;
                padding: 10px;
            }}

            #taglineLabel {{
                color: {c.text_on_primary};
                font-size: 14px;
                margin-top: 8px;
            }}

            #contentArea {{
                background-color: {c.bg_primary};
                border-top-left-radius: 20px;
                border-top-right-radius: 20px;
                margin-top: -20px;
            }}

            #welcomeLabel {{
                font-size: 24px;
                font-weight: bold;
                color: {c.text_primary};
            }}

            #welcomeLabel[fontSize="20"] {{ font-size: 20px; }}
            #welcomeLabel[fontSize="22"] {{ font-size: 22px; }}
            #welcomeLabel[fontSize="24"] {{ font-size: 24px; }}

            #subtitleLabel {{
                font-size: 14px;
                color: {c.text_secondary};
            }}

            #subtitleLabel[fontSize="12"] {{ font-size: 12px; }}
            #subtitleLabel[fontSize="13"] {{ font-size: 13px; }}
            #subtitleLabel[fontSize="14"] {{ font-size: 14px; }}

            #inputLabel {{
                font-size: 13px;
                font-weight: 600;
                color: {c.text_primary};
            }}

            #inputFrame {{
                background-color: {c.bg_input};
                border: 2px solid {c.border_default};
                border-radius: 8px;
                min-height: 44px;
                padding: 8px 12px;
            }}

            #inputFrame:focus-within {{
                border-color: {c.border_focus};
                background-color: {c.bg_input_focus};
            }}

            #inputField {{
                background: transparent;
                border: none;
                font-size: 14px;
                color: {c.text_primary};
                min-height: 28px;
            }}

            #inputField::placeholder {{
                color: {c.text_placeholder};
            }}

            #iconLabel {{
                font-size: 18px;
            }}

            #togglePasswordBtn {{
                background: transparent;
                border: none;
                font-size: 16px;
                color: {c.text_secondary};
            }}

            #togglePasswordBtn:hover {{
                background-color: {c.bg_input};
                border-radius: 4px;
            }}

            #loginButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c.accent_primary}, stop:1 {c.accent_secondary});
                color: {c.text_on_primary};
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 20px;
                min-height: 44px;
            }}

            #loginButton:hover {{
                background: {c.accent_hover};
            }}

            #loginButton:disabled {{
                background-color: {c.border_default};
                color: {c.text_placeholder};
            }}

            #progressFrame {{
                background-color: {c.progress_bg};
                border: 1px solid {c.border_default};
                border-radius: 8px;
                padding: 12px;
            }}

            #progressStep {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px 8px;
            }}

            #progressStep[state="active"] {{
                background-color: {c.progress_active};
            }}

            #progressStep[state="complete"] {{
                background-color: {c.progress_complete};
            }}

            #progressStep[state="error"] {{
                background-color: {c.progress_error};
            }}

            #stepLabel {{
                font-size: 13px;
                color: {c.text_primary};
            }}

            #overallProgress {{
                border: none;
                background-color: {c.border_default};
                border-radius: 3px;
                min-height: 6px;
                max-height: 6px;
            }}

            #overallProgress::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c.accent_primary}, stop:1 {c.accent_secondary});
                border-radius: 3px;
            }}

            #statusLabel {{
                font-size: 13px;
                padding: 10px;
                border-radius: 6px;
            }}

            #statusLabel[status="error"] {{
                color: {c.error_text};
                background-color: {c.error_bg};
            }}

            #statusLabel[status="success"] {{
                color: {c.success_text};
                background-color: {c.success_bg};
            }}

            #hintLabel {{
                font-size: 12px;
                color: {c.text_secondary};
            }}

            #helpLabel {{
                font-size: 12px;
                color: {c.text_secondary};
            }}

            #helpLabel a {{
                color: {c.accent_primary};
                text-decoration: none;
            }}

            QScrollArea {{
                border: none;
                background-color: transparent;
            }}

            QScrollBar:vertical {{
                background-color: {c.bg_input};
                width: 10px;
                border-radius: 5px;
            }}

            QScrollBar::handle:vertical {{
                background-color: {c.border_default};
                border-radius: 5px;
                min-height: 20px;
            }}

            QScrollBar::handle:vertical:hover {{
                background-color: {c.text_placeholder};
            }}
        """

        self.setStyleSheet(stylesheet)


class EnhancedLoginThread(QThread):
    """Login thread"""
    status_update = pyqtSignal(int, str, int)
    step_complete = pyqtSignal(int)
    login_complete = pyqtSignal(bool, str, object, object, object)

    def __init__(self, subdomain, email, password):
        super().__init__()
        self.subdomain = subdomain
        self.email = email
        self.password = password

    def run(self):
        """Authenticate"""
        try:
            from primebooks.auth import DesktopAuthManager

            self.status_update.emit(0, "Connecting to server...", 10)
            self.msleep(300)

            auth_manager = DesktopAuthManager()
            self.step_complete.emit(0)

            self.status_update.emit(1, "Authenticating credentials...", 30)
            success, result = auth_manager.authenticate(
                subdomain=self.subdomain,
                email=self.email,
                password=self.password
            )

            if not success:
                error_message = result.get('error', 'Authentication failed')
                self.login_complete.emit(False, error_message, None, None, None)
                return

            self.step_complete.emit(1)

            self.status_update.emit(2, "Syncing workspace data...", 60)
            token = result.get('token')
            user_data = result.get('user')
            company_data = result.get('company')

            self.msleep(500)
            self.step_complete.emit(2)

            self.status_update.emit(3, "Finalizing login...", 85)
            auth_manager.save_credentials(user_data, company_data, token)

            self.msleep(300)
            self.step_complete.emit(3)

            self.status_update.emit(3, "Complete!", 100)
            self.login_complete.emit(True, "Success", token, user_data, company_data)

        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            self.login_complete.emit(False, f"Connection error: {str(e)}", None, None, None)


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

# ============================================================================
# MIGRATION PROGRESS DIALOG
# ============================================================================

# ============================================================================
# MIGRATION PROGRESS DIALOG
# ============================================================================

class MigrationThread(QThread):
    status_update = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = data_dir

    def run(self):
        try:
            from django.core.management import call_command
            from django.db import connection

            self.status_update.emit("Creating database schema...")
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS public;")

            self.status_update.emit("Setting up PrimeBooks Desktop...")
            call_command(
                'migrate_schemas',
                schema_name='public',
                interactive=False,
                verbosity=0
            )

            self.status_update.emit("Database ready!")
            (self.data_dir / '.initialized').touch()
            self.finished.emit(True, "")

        except Exception as e:
            logger.error(f"Migration error: {e}", exc_info=True)
            self.finished.emit(False, str(e))


class MigrationSetupDialog(QDialog):
    """Shown on first run while migrations execute — spinner style"""

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.success = False
        self._angle = 0

        self.setWindowTitle("PrimeBooks — First Time Setup")
        self.setModal(True)
        self.setFixedSize(420, 260)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self._build_ui()
        self._apply_theme()

        # Spinner animation timer
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick_spinner)
        self._spin_timer.start(30)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 35, 40, 35)
        layout.setSpacing(16)

        title = QLabel("⚙️  Setting Up Your PrimeBooks")
        title.setObjectName("migTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        note = QLabel("This only happens once — please don't close the app.")
        note.setObjectName("migNote")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(note)

        # Spinner canvas
        self._spinner = QLabel()
        self._spinner.setFixedSize(56, 56)
        self._spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status = QLabel("Initializing...")
        self.status.setObjectName("migStatus")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addStretch()

    def _tick_spinner(self):
        """Draw a rotating arc as the spinner"""
        from PyQt6.QtGui import QPainter, QColor, QPen
        from PyQt6.QtCore import QRect

        self._angle = (self._angle + 8) % 360

        size = 56
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))  # transparent

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background circle
        pen = QPen(QColor("#2d3748"), 5)
        painter.setPen(pen)
        margin = 6
        rect = QRect(margin, margin, size - margin * 2, size - margin * 2)
        painter.drawEllipse(rect)

        # Spinning arc
        pen = QPen(QColor("#667eea"), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # Qt drawArc uses 1/16th degrees, starts from 3 o'clock, goes counter-clockwise
        start_angle = (90 - self._angle) * 16   # rotate so it starts from top
        span_angle = -100 * 16                   # arc length ~100 degrees
        painter.drawArc(rect, start_angle, span_angle)

        painter.end()
        self._spinner.setPixmap(pixmap)

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1a202c;
            }
            #migTitle {
                color: #f7fafc;
                font-size: 17px;
                font-weight: bold;
            }
            #migNote {
                color: #a0aec0;
                font-size: 12px;
            }
            #migStatus {
                color: #cbd5e0;
                font-size: 13px;
            }
        """)

    def run(self):
        """Start migration thread and show dialog. Returns True on success."""
        self.thread = MigrationThread(self.data_dir)
        self.thread.status_update.connect(self._on_status)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()
        self.exec()
        return self.success

    def _on_status(self, message):
        self.status.setText(message)

    def _on_finished(self, success, error):
        self._spin_timer.stop()
        self.success = success
        if not success:
            QMessageBox.critical(
                self,
                "Setup Failed",
                f"Database setup failed:\n\n{error}\n\nPlease restart the app."
            )
        self.accept()

def initialize_django(data_dir):
    """Setup Django. Migrations are handled separately via MigrationSetupDialog."""
    logger.info("Initializing Django in desktop mode")
    import django
    django.setup()
    logger.info("Django apps loaded")
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


class CustomWebEnginePage(QWebEnginePage):
    """Custom page to handle print links"""

    def __init__(self, parent_window, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_window = parent_window

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        """
        Intercept navigation requests to handle print links
        """
        url_string = url.toString()

        # Check if this is a print receipt URL
        if '/print-receipt/' in url_string or '/print_receipt/' in url_string:
            logger.info(f"🖨️ Print request intercepted: {url_string}")

            # Extract sale ID from URL
            # URL format: /sales/123/print-receipt/
            try:
                parts = url_string.split('/')
                sale_id_index = parts.index('sales') + 1 if 'sales' in parts else -1

                if sale_id_index > 0 and sale_id_index < len(parts):
                    sale_id = parts[sale_id_index]
                    logger.info(f"📄 Triggering PDF export for sale #{sale_id}")

                    # Trigger PDF export instead of navigation
                    self.parent_window.print_to_pdf_simple()

                    # Prevent navigation
                    return False

            except Exception as e:
                logger.error(f"Error parsing print URL: {e}")

        # Allow all other navigation
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


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
        self.current_user_email = None

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

        # ✅ Set window icon explicitly at runtime (required for taskbar/titlebar)
        icon_path = find_icon()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
            logger.info(f"✅ Window icon set from: {icon_path}")
        else:
            logger.warning("⚠️  No icon file found for main window")

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

        # ✅ NEW: Connect load handler for print interception
        self.browser.loadFinished.connect(self.on_page_loaded)

        self.setCentralWidget(self.browser)

        QTimer.singleShot(1000, self.load_application)

    def on_page_loaded(self, success):
        """Inject print handler when page loads"""
        if success:
            logger.info("📄 Page loaded successfully")

            # Wait a bit for DOM to be ready
            QTimer.singleShot(500, self.inject_print_handler)

    def background_sync(self):
        """Start background sync - non-blocking"""
        try:
            logger.info("🔄 Starting background sync...")

            # Import the new components
            from primebooks.background_sync_worker import BackgroundSyncWorker
            from primebooks.detailed_sync_dialog import DetailedSyncDialog

            # Create non-modal progress dialog
            self.sync_dialog = DetailedSyncDialog(parent=self)

            # Create background worker
            self.sync_worker = BackgroundSyncWorker(
                tenant_id=self.tenant_id,
                schema_name=self.subdomain,
                auth_token=self.auth_token,
                sync_type="full"
            )

            # Connect all signals
            self.sync_worker.sync_started.connect(self.sync_dialog.on_sync_started)
            self.sync_worker.phase_changed.connect(self.sync_dialog.on_phase_changed)
            self.sync_worker.model_started.connect(self.sync_dialog.on_model_started)
            self.sync_worker.model_progress.connect(self.sync_dialog.on_model_progress)
            self.sync_worker.model_completed.connect(self.sync_dialog.on_model_completed)
            self.sync_worker.overall_progress.connect(self.sync_dialog.on_overall_progress)
            self.sync_worker.error_occurred.connect(self.sync_dialog.on_error)
            self.sync_worker.warning_occurred.connect(self.sync_dialog.on_warning)
            self.sync_worker.sync_completed.connect(self.on_background_sync_completed)

            # Connect cancel button
            self.sync_dialog.cancel_btn.clicked.connect(self.sync_worker.cancel)

            # Show dialog (non-modal)
            self.sync_dialog.show()

            # Start worker thread
            self.sync_worker.start()

            # Update status bar
            self.statusBar.showMessage("🔄 Background sync in progress...", 3000)

        except Exception as e:
            logger.error(f"Failed to start background sync: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Sync Error",
                f"Failed to start background sync:\n\n{str(e)}"
            )

    def on_background_sync_completed(self, success, summary):
        """Handle background sync completion"""
        if success:
            # Show system notification
            self.show_system_notification(
                "Sync Complete",
                f"✅ Synced successfully!\n"
                f"Created: {summary.get('created', 0)}, "
                f"Updated: {summary.get('updated', 0)}"
            )

            # Refresh the page
            QTimer.singleShot(2000, self.browser.reload)

            # Update status bar
            self.statusBar.showMessage(
                f"✅ Sync complete! Created: {summary.get('created', 0)}, "
                f"Updated: {summary.get('updated', 0)}",
                5000
            )
        else:
            # Show error notification
            error_msg = summary.get('message', 'Unknown error')
            self.show_system_notification(
                "Sync Failed",
                f"❌ Sync failed: {error_msg}",
                is_error=True
            )

    def show_system_notification(self, title, message, is_error=False):
        """Show system tray notification"""
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon
            from PyQt6.QtGui import QIcon

            if QSystemTrayIcon.isSystemTrayAvailable():
                # Create tray icon if not exists
                if not hasattr(self, 'tray_icon'):
                    self.tray_icon = QSystemTrayIcon(self)
                    # Set icon (you'll need to provide an icon file)
                    # self.tray_icon.setIcon(QIcon("path/to/icon.png"))
                    self.tray_icon.show()

                # Show notification
                icon_type = QSystemTrayIcon.MessageIcon.Critical if is_error else QSystemTrayIcon.MessageIcon.Information
                self.tray_icon.showMessage(
                    title,
                    message,
                    icon_type,
                    5000  # 5 seconds
                )
            else:
                # Fallback to message box if system tray not available
                logger.info(f"Notification: {title} - {message}")
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")

    def inject_print_handler(self):
        """Inject JavaScript to intercept print links"""
        js_code = """
        (function() {
            if (window.__printHandlerInstalled) return;

            document.addEventListener('click', function(e) {
                const link = e.target.closest('a');
                if (!link) return;

                const href = link.getAttribute('href') || '';

                if (href.includes('print-receipt') || href.includes('print_receipt')) {
                    e.preventDefault();
                    e.stopPropagation();

                    console.log('📄 Print request:', href);

                    // Call Python handler via window.pywebchannel if available
                    // Otherwise, post message
                    if (window.printHandler) {
                        window.printHandler.handlePrint(href);
                    } else {
                        // Fallback: navigate to receipt page
                        window.__navigatingToPrint = true;
                        window.location.href = href;
                    }

                    return false;
                }
            }, true);

            window.__printHandlerInstalled = true;
        })();
        """

        self.browser.page().runJavaScript(js_code)

    def handle_print_request(self, receipt_url):
        """
        Handle print request by:
        1. Creating hidden browser
        2. Loading receipt
        3. Printing
        4. Closing hidden browser
        """
        logger.info(f"🖨️ Handling print request: {receipt_url}")

        # Create hidden browser for receipt
        self.print_browser = QWebEngineView()
        self.print_browser.hide()

        # Connect load handler
        def on_receipt_loaded(success):
            if success:
                logger.info("✅ Receipt loaded, printing...")

                # Wait a bit for rendering
                QTimer.singleShot(1000, lambda: self.print_receipt_in_hidden_browser())

        self.print_browser.loadFinished.connect(on_receipt_loaded)

        # Load receipt URL
        full_url = f"http://{self.subdomain}.localhost:{self.port}{receipt_url}"
        self.print_browser.setUrl(QUrl(full_url))

    def print_receipt_in_hidden_browser(self):
        """Print from hidden browser"""
        logger.info("🖨️ Printing from hidden browser...")

        import tempfile
        from pathlib import Path

        timestamp = int(time.time())
        pdf_path = Path(tempfile.gettempdir()) / f"receipt_{timestamp}.pdf"

        # Print to PDF
        self.print_browser.page().printToPdf(str(pdf_path))

        # Wait, then open PDF
        QTimer.singleShot(2000, lambda: self.open_receipt_pdf(pdf_path))

        # Clean up hidden browser
        QTimer.singleShot(3000, lambda: self.cleanup_print_browser())

    def open_receipt_pdf(self, pdf_path):
        """Open the printed receipt PDF"""
        import subprocess
        import platform

        if not pdf_path.exists():
            logger.warning(f"PDF not ready yet: {pdf_path}")
            # Try again
            QTimer.singleShot(1000, lambda: self.open_receipt_pdf(pdf_path))
            return

        logger.info(f"📄 Opening receipt: {pdf_path}")

        try:
            if platform.system() == 'Windows':
                os.startfile(str(pdf_path))
            elif platform.system() == 'Darwin':
                subprocess.run(['open', str(pdf_path)])
            else:
                subprocess.run(['xdg-open', str(pdf_path)])

            self.statusBar.showMessage(f"✅ Receipt opened: {pdf_path.name}", 5000)
        except Exception as e:
            logger.error(f"Failed to open PDF: {e}")

    def cleanup_print_browser(self):
        """Clean up hidden browser"""
        if hasattr(self, 'print_browser'):
            self.print_browser.deleteLater()
            delattr(self, 'print_browser')
            logger.info("🗑️ Print browser cleaned up")

    def setup_print_support(self):
        """Setup print functionality for web pages"""
        self.browser.page().printRequested.connect(self.handle_print_request)
        logger.info("✅ Print support enabled (JavaScript window.print() intercept)")

    def setup_update_manager(self):
        """Initialize auto-update manager"""
        try:
            from django.conf import settings
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
        """
        Switch to a different user account without restarting the app.

        Flow:
          1. Show UserSwitchDialog — authenticates against the server
          2. Save new credentials to disk (middleware reads these on every request)
          3. Clear the browser's session cookies so the old session is gone
          4. Reload — desktop_tenant middleware auto-logs in the new user,
             syncing them on-demand if they don't exist locally yet
        """
        logger.info("🔄 User switch requested")

        try:
            from primebooks.auth import DesktopAuthManager
            from django.conf import settings

            # Non-critical subscription pre-check
            try:
                from primebooks.subscription import SubscriptionManager
                sub_manager = SubscriptionManager(company_id=self.tenant_id)
                valid, reason, *_ = sub_manager.validate_subscription(force_online=False)
                if not valid:
                    QMessageBox.warning(self, "Subscription Issue", reason)
                    return
            except Exception as e:
                logger.warning(f"Subscription pre-check failed (non-fatal): {e}")

            dialog = UserSwitchDialog(
                company_schema=self.subdomain,
                company_id=self.tenant_id,
                parent=self
            )

            if dialog.exec() != QDialog.DialogCode.Accepted:
                logger.info("User switch cancelled")
                return

            new_user_data = dialog.user_data
            new_token = dialog.auth_token
            new_email = new_user_data.get('email', '')

            if not new_email or not new_token:
                QMessageBox.warning(
                    self,
                    "Switch User",
                    "Incomplete user data returned. Please try again."
                )
                return

            old_email = getattr(self, 'current_user_email', None) or 'previous user'
            logger.info(f"✅ Switching user: {old_email} → {new_email}")

            auth_manager = DesktopAuthManager()

            # Company doesn't change on user switch — keep existing company data
            _, _, existing_company_data = auth_manager.load_credentials()

            # Persist new credentials — middleware reads these on every request
            auth_manager.save_credentials(new_user_data, existing_company_data, new_token)
            auth_manager.save_auth_token(new_token)  # keeps .auth_token plain file current
            auth_manager.save_user_info(new_user_data)  # middleware reads this for auto-login

            # Re-save subdomain — must stay intact for middleware tenant lookup
            subdomain = auth_manager.get_subdomain() or self.subdomain
            auth_manager.save_subdomain(subdomain)

            # Update in-memory state
            self.auth_token = new_token
            self.current_user_email = new_email

            # Update sync scheduler so future syncs use the new token
            if self.sync_scheduler:
                try:
                    self.sync_scheduler.auth_token = new_token
                except Exception:
                    pass

            # Clear cookies then reload
            self._clear_browser_session(
                on_done=lambda: self._finish_user_switch(new_email)
            )

        except Exception as e:
            logger.error(f"User switch error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Switch User Error",
                f"Failed to switch user:\n\n{str(e)}"
            )

    def _clear_browser_session(self, on_done):
        """
        Clear all session cookies in the web engine profile so the old
        Django session is invalidated before we reload.
        The middleware no longer relies on session — it reads credentials
        from disk on every request — so this just ensures Django doesn't
        reuse the old user's server-side session object.
        """
        try:
            profile = self.browser.page().profile()
            cookie_store = profile.cookieStore()
            cookie_store.deleteAllCookies()
            logger.info("🍪 Browser session cookies cleared")

            # 800ms delay — gives credential files time to fully flush to disk
            # before the middleware reads them on the next request
            QTimer.singleShot(800, on_done)

        except Exception as e:
            logger.warning(f"Could not clear cookies (non-fatal): {e}")
            # Proceed anyway with delay
            QTimer.singleShot(800, on_done)

    def _finish_user_switch(self, new_email):
        """
        Called after cookies are cleared and credential files are written.
        Updates the UI and navigates to the home page.
        The middleware will:
          1. Read new credentials from disk → find tenant
          2. Call auto_login_user → find or on-demand sync the new user
          3. Log them in automatically
        """
        # Update toolbar label
        self.status_label.setText(f"● {self.subdomain} — {new_email}")
        self.statusBar.showMessage(f"✅ Logged in as {new_email}", 5000)

        # Navigate using the full subdomain URL — this is what the middleware
        # uses to identify the tenant via the HOST header
        home_url = f"http://{self.subdomain}.localhost:{self.port}/"
        logger.info(f"🔄 Reloading app as {new_email} → {home_url}")

        self.browser.setUrl(QUrl(home_url))
        logger.info(f"✅ User switch complete → {new_email}")

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

        sync_action = QAction("🔄 Sync Data (Background)", self)
        sync_action.triggered.connect(self.background_sync)
        toolbar.addAction(sync_action)

        toolbar.addSeparator()

        switch_user_action = QAction("👥 Switch User", self)
        switch_user_action.triggered.connect(self.switch_user)
        toolbar.addAction(switch_user_action)

        toolbar.addSeparator()

        # Status label — populated with real email once credentials load
        self.status_label = QLabel(f"● {self.subdomain}")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        toolbar.addWidget(self.status_label)

        toolbar.addSeparator()

        logout_action = QAction("🚪 Logout", self)
        logout_action.triggered.connect(self.logout)
        toolbar.addAction(logout_action)

        # Populate current user email from saved credentials
        try:
            from primebooks.auth import DesktopAuthManager
            _, saved_user, _ = DesktopAuthManager().load_credentials()
            if saved_user and saved_user.get('email'):
                self.current_user_email = saved_user['email']
                self.status_label.setText(f"● {self.subdomain} — {self.current_user_email}")
        except Exception:
            pass

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

        # ✅ Set app-wide icon at runtime (controls taskbar, Alt+Tab, titlebar)
        icon_path = find_icon()
        if icon_path:
            app.setWindowIcon(QIcon(icon_path))
            logger.info(f"✅ App icon set from: {icon_path}")
        else:
            logger.warning("⚠️  No icon file found — window will use default icon")

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
        if icon_path:
            progress.setWindowIcon(QIcon(icon_path))
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

            # Show migration dialog on first run
            if not (data_dir / '.initialized').exists():
                logger.info("First run — showing migration setup dialog...")
                mig_dialog = MigrationSetupDialog(data_dir)
                if not mig_dialog.run():
                    app.quit()
                    return
                logger.info("✅ First-run migrations complete")
            else:
                logger.info("Database already initialized — skipping migrations")

            # Authentication
            from primebooks.auth import DesktopAuthManager
            auth_manager = DesktopAuthManager()

            saved_token, saved_user, saved_company = auth_manager.load_credentials()
            token, company_data, subdomain, tenant_id = None, None, None, None

            if not saved_token or not saved_company:
                logger.info("No saved credentials found. Opening login...")
                login_dialog = ThemedLoginDialog(theme=Theme.DARK)
                if icon_path:
                    login_dialog.setWindowIcon(QIcon(icon_path))
                if login_dialog.exec() != QDialog.DialogCode.Accepted:
                    app.quit()
                    return

                token = login_dialog.auth_token
                company_data = login_dialog.company_data
                user_data = login_dialog.user_data

                # ✅ FIXED: Get subdomain from auth_manager, not company_data
                subdomain = auth_manager.get_subdomain()
                tenant_id = company_data.get('company_id')

                auth_manager.save_credentials(user_data, company_data, token)

                sync_dialog = DataSyncDialog(subdomain, token, company_data)
                if icon_path:
                    sync_dialog.setWindowIcon(QIcon(icon_path))
                sync_dialog.exec()
            else:
                logger.info("Using saved credentials...")
                token = saved_token
                company_data = saved_company
                user_data = saved_user

                # ✅ FIXED: Get subdomain from auth_manager, not company_data
                subdomain = auth_manager.get_subdomain()
                tenant_id = company_data.get('company_id')

                if not subdomain or not tenant_id:
                    logger.info("Invalid saved credentials. Showing login...")
                    auth_manager.logout()

                    login_dialog = ThemedLoginDialog(theme=Theme.DARK)
                    if icon_path:
                        login_dialog.setWindowIcon(QIcon(icon_path))
                    if login_dialog.exec() != QDialog.DialogCode.Accepted:
                        app.quit()
                        return

                    token = login_dialog.auth_token
                    company_data = login_dialog.company_data
                    user_data = login_dialog.user_data

                    # ✅ FIXED: Get subdomain from auth_manager, not company_data
                    subdomain = auth_manager.get_subdomain()
                    tenant_id = company_data.get('company_id')

                    auth_manager.save_credentials(user_data, company_data, token)

                    sync_dialog = DataSyncDialog(subdomain, token, company_data)
                    if icon_path:
                        sync_dialog.setWindowIcon(QIcon(icon_path))
                    sync_dialog.exec()

                    # ✅ NEW: Reset sequences after initial sync (safety net)
                    logger.info("🔄 Resetting sequences on startup (safety net)...")
                    try:
                        from primebooks.sync import SyncManager
                        sync_manager = SyncManager(
                            tenant_id=tenant_id,
                            schema_name=subdomain,
                            auth_token=token
                        )
                        sync_manager.reset_sequences()
                        logger.info("✅ Sequences reset on startup")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not reset sequences on startup: {e}")

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
            if icon_path:
                progress_dialog.setWindowIcon(QIcon(icon_path))
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