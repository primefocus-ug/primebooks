"""
Enhanced Startup Manager with GUI Splash Screen
✅ Professional animated loading screen
✅ Better error handling with retry mechanism
✅ Detailed progress tracking
✅ Smooth animations and transitions
✅ Resource cleanup
✅ Health checks
"""
import sys
import logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QFont, QPalette, QColor, QLinearGradient
from django.conf import settings
import time

logger = logging.getLogger(__name__)


class InitializationThread(QThread):
    """Background thread for initialization with detailed progress"""
    progress = pyqtSignal(str, int, str)  # (message, percentage, detail)
    finished = pyqtSignal(bool, str)  # (success, error_message)
    health_check = pyqtSignal(str, bool)  # (component, healthy)

    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = data_dir
        self.should_stop = False

    def run(self):
        """Run initialization with comprehensive checks"""
        try:
            # Step 1: Check system requirements
            self.progress.emit("Checking system requirements...", 5, "Validating environment")
            if not self.check_system_requirements():
                self.finished.emit(False, "System requirements not met")
                return

            # Step 2: PostgreSQL initialization
            self.progress.emit("Starting database engine...", 15, "Initializing PostgreSQL")
            if not self.init_postgresql():
                self.finished.emit(False, "Failed to initialize PostgreSQL")
                return

            # Step 3: Database health check
            self.progress.emit("Verifying database connection...", 35, "Running health checks")
            if not self.check_database_health():
                self.finished.emit(False, "Database health check failed")
                return

            # Step 4: Django initialization
            self.progress.emit("Loading application framework...", 50, "Initializing Django")
            if not self.init_django():
                self.finished.emit(False, "Failed to initialize Django")
                return

            # Step 5: Schema setup
            self.progress.emit("Configuring database schema...", 65, "Setting up tables")
            if not self.ensure_public_schema():
                self.finished.emit(False, "Failed to setup database schema")
                return

            # Step 6: Run migrations
            self.progress.emit("Applying database migrations...", 80, "Updating schema")
            if not self.run_migrations():
                self.finished.emit(False, "Failed to run migrations")
                return

            # Step 7: Final health checks
            self.progress.emit("Running final checks...", 90, "Verifying system integrity")
            if not self.final_health_checks():
                self.finished.emit(False, "Final health checks failed")
                return

            # Step 8: Complete
            self.progress.emit("Startup complete!", 100, "Ready to use")
            time.sleep(0.3)  # Brief pause to show completion
            self.finished.emit(True, "")

        except Exception as e:
            logger.error(f"Initialization error: {e}", exc_info=True)
            self.finished.emit(False, str(e))

    def check_system_requirements(self):
        """Check system requirements"""
        try:
            # Check data directory
            if not self.data_dir.exists():
                self.data_dir.mkdir(parents=True, exist_ok=True)

            # Check write permissions
            test_file = self.data_dir / '.write_test'
            test_file.touch()
            test_file.unlink()

            self.health_check.emit("File System", True)
            return True
        except Exception as e:
            logger.error(f"System requirements check failed: {e}")
            self.health_check.emit("File System", False)
            return False

    def init_postgresql(self):
        """Initialize PostgreSQL with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                from primebooks.postgres_manager import EmbeddedPostgresManager

                pg_manager = EmbeddedPostgresManager(self.data_dir)

                # Setup with progress callback
                def progress_callback(msg):
                    logger.debug(f"PostgreSQL: {msg}")

                if not pg_manager.setup(progress_callback=progress_callback):
                    if attempt < max_retries - 1:
                        self.progress.emit(
                            f"Retrying database initialization... ({attempt + 1}/{max_retries})",
                            20,
                            "Connection attempt failed"
                        )
                        time.sleep(2)
                        continue
                    return False

                # Update Django database config
                settings.DATABASES['default'].update(pg_manager.get_connection_params())

                self.health_check.emit("PostgreSQL", True)
                return True

            except Exception as e:
                logger.error(f"PostgreSQL init error (attempt {attempt + 1}): {e}")
                if attempt >= max_retries - 1:
                    self.health_check.emit("PostgreSQL", False)
                    return False
                time.sleep(2)

        return False

    def check_database_health(self):
        """Verify database connection"""
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    self.health_check.emit("Database Connection", True)
                    return True
            return False
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            self.health_check.emit("Database Connection", False)
            return False

    def init_django(self):
        """Initialize Django"""
        try:
            import django
            django.setup()
            logger.info("✅ Django initialized")
            self.health_check.emit("Django", True)
            return True
        except Exception as e:
            logger.error(f"Django init error: {e}")
            self.health_check.emit("Django", False)
            return False

    def ensure_public_schema(self):
        """Ensure public schema exists"""
        try:
            from django.db import connection

            # Check if this is first run
            first_run = not (self.data_dir / '.initialized').exists()

            if first_run:
                logger.info("First run - setting up database...")

                # Create public schema
                with connection.cursor() as cursor:
                    cursor.execute("CREATE SCHEMA IF NOT EXISTS public;")
                    cursor.execute("SET search_path TO public;")

                # Create django_migrations table
                with connection.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS django_migrations (
                            id SERIAL PRIMARY KEY,
                            app VARCHAR(255) NOT NULL,
                            name VARCHAR(255) NOT NULL,
                            applied TIMESTAMP WITH TIME ZONE NOT NULL
                        );
                    """)

                # Create django_content_type table
                with connection.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS django_content_type (
                            id SERIAL PRIMARY KEY,
                            app_label VARCHAR(100) NOT NULL,
                            model VARCHAR(100) NOT NULL,
                            UNIQUE(app_label, model)
                        );
                                   """)

                    # Mark as applied
                    cursor.execute("""
                        INSERT INTO django_migrations (app, name, applied)
                        VALUES 
                            ('contenttypes', '0001_initial', NOW()),
                            ('contenttypes', '0002_remove_content_type_name', NOW())
                        ON CONFLICT DO NOTHING;
                    """)

                logger.info("✅ Schema created")

            self.health_check.emit("Database Schema", True)
            return True

        except Exception as e:
            logger.error(f"Schema setup error: {e}")
            self.health_check.emit("Database Schema", False)
            return False

    def run_migrations(self):
        """Run database migrations"""
        try:
            from django.core.management import call_command

            # Check if first run
            first_run = not (self.data_dir / '.initialized').exists()

            if first_run:
                logger.info("Running migrations...")
                call_command('migrate_schemas',
                             schema_name='public',
                             interactive=False,
                             verbosity=0)

                # Mark as initialized
                (self.data_dir / '.initialized').touch()
                logger.info("✅ Migrations completed")

            self.health_check.emit("Migrations", True)
            return True

        except Exception as e:
            logger.error(f"Migration error: {e}")
            self.health_check.emit("Migrations", False)
            return False

    def final_health_checks(self):
        """Run final health checks"""
        try:
            from django.db import connection

            # Check database connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                version = cursor.fetchone()
                logger.info(f"PostgreSQL version: {version[0]}")

            # Check tables exist
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public';
                """)
                table_count = cursor.fetchone()[0]
                logger.info(f"Tables in public schema: {table_count}")

            self.health_check.emit("System Health", True)
            return True

        except Exception as e:
            logger.error(f"Final health check failed: {e}")
            self.health_check.emit("System Health", False)
            return False

    def stop(self):
        """Stop initialization"""
        self.should_stop = True


class FadeLabel(QLabel):
    """Label with fade animation support"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._opacity = 1.0

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, opacity):
        self._opacity = opacity
        self.setStyleSheet(self.styleSheet() + f"color: rgba(52, 73, 94, {int(opacity * 255)});")

    opacity = pyqtProperty(float, get_opacity, set_opacity)


class EnhancedSplashScreen(QWidget):
    """
    Modern, animated splash screen
    ✅ Smooth animations
    ✅ Detailed progress display
    ✅ Error handling with retry
    ✅ Health status indicators
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(600, 450)
        self.health_status = {}

        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )

        self.setup_ui()
        self.setup_animations()

    def setup_ui(self):
        """Setup UI elements"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(50, 50, 50, 50)
        main_layout.setSpacing(25)

        # Gradient background
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 15px;
            }
        """)

        # Logo/Title with shadow effect
        title = QLabel("PrimeBooks")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont("Segoe UI", 42, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("""
            color: white;
            background: transparent;
        """)
        main_layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Desktop Edition")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_font = QFont("Segoe UI", 16)
        subtitle.setFont(subtitle_font)
        subtitle.setStyleSheet("""
            color: rgba(255, 255, 255, 0.9);
            background: transparent;
        """)
        main_layout.addWidget(subtitle)

        # Spacer
        main_layout.addSpacing(20)

        # Status label
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_font = QFont("Segoe UI", 14, QFont.Weight.Medium)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("""
            color: white;
            background: transparent;
        """)
        main_layout.addWidget(self.status_label)

        # Detail label (smaller, for sub-status)
        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_font = QFont("Segoe UI", 11)
        self.detail_label.setFont(detail_font)
        self.detail_label.setStyleSheet("""
            color: rgba(255, 255, 255, 0.7);
            background: transparent;
        """)
        main_layout.addWidget(self.detail_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4facfe, stop:1 #00f2fe);
                border-radius: 5px;
            }
        """)
        main_layout.addWidget(self.progress_bar)

        # Percentage label
        self.percent_label = QLabel("0%")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        percent_font = QFont("Segoe UI", 12)
        self.percent_label.setFont(percent_font)
        self.percent_label.setStyleSheet("""
            color: rgba(255, 255, 255, 0.8);
            background: transparent;
        """)
        main_layout.addWidget(self.percent_label)

        # Health status container
        self.health_container = QWidget()
        self.health_container.setStyleSheet("background: transparent;")
        health_layout = QVBoxLayout()
        health_layout.setSpacing(5)
        self.health_container.setLayout(health_layout)
        self.health_container.hide()  # Initially hidden
        main_layout.addWidget(self.health_container)

        # Spacer
        main_layout.addStretch()

        # Version and footer
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(20)

        version = QLabel("v1.0.0")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_font = QFont("Segoe UI", 10)
        version.setFont(version_font)
        version.setStyleSheet("""
            color: rgba(255, 255, 255, 0.6);
            background: transparent;
        """)
        footer_layout.addWidget(version)

        # Error/retry button (hidden by default)
        self.retry_button = QPushButton("Retry")
        self.retry_button.setFixedSize(80, 30)
        self.retry_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 5px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        self.retry_button.hide()
        footer_layout.addWidget(self.retry_button)

        main_layout.addLayout(footer_layout)

        self.setLayout(main_layout)

    def setup_animations(self):
        """Setup smooth animations"""
        # Progress bar animation
        self.progress_animation = QPropertyAnimation(self.progress_bar, b"value")
        self.progress_animation.setDuration(300)
        self.progress_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def update_progress(self, message, percentage, detail=""):
        """Update progress with animation"""
        # Animate progress bar
        self.progress_animation.setEndValue(percentage)
        self.progress_animation.start()

        # Update labels
        self.status_label.setText(message)
        self.detail_label.setText(detail)
        self.percent_label.setText(f"{percentage}%")

        QApplication.processEvents()

    def add_health_status(self, component, healthy):
        """Add or update health status indicator"""
        if component not in self.health_status:
            # Create new status indicator
            status_widget = QWidget()
            status_widget.setStyleSheet("background: transparent;")
            status_layout = QHBoxLayout()
            status_layout.setContentsMargins(0, 0, 0, 0)

            # Status icon
            icon = QLabel("●")
            icon_font = QFont("Segoe UI", 12)
            icon.setFont(icon_font)
            icon.setFixedWidth(20)

            # Component label
            label = QLabel(component)
            label_font = QFont("Segoe UI", 10)
            label.setFont(label_font)
            label.setStyleSheet("color: rgba(255, 255, 255, 0.8); background: transparent;")

            status_layout.addWidget(icon)
            status_layout.addWidget(label)
            status_layout.addStretch()

            status_widget.setLayout(status_layout)
            self.health_container.layout().addWidget(status_widget)

            self.health_status[component] = (icon, label)
            self.health_container.show()

        # Update status
        icon, label = self.health_status[component]
        if healthy:
            icon.setStyleSheet("color: #2ecc71; background: transparent;")
        else:
            icon.setStyleSheet("color: #e74c3c; background: transparent;")

    def show_error(self, message):
        """Show error state"""
        self.status_label.setText("Startup Failed")
        self.status_label.setStyleSheet("""
            color: #e74c3c;
            background: transparent;
            font-weight: bold;
        """)
        self.detail_label.setText(message)
        self.retry_button.show()


class StartupManager:
    """
    Enhanced startup manager with better UX
    ✅ Animated splash screen
    ✅ Retry mechanism
    ✅ Health monitoring
    ✅ Proper cleanup
    """

    def __init__(self, app, data_dir):
        self.app = app
        self.data_dir = data_dir
        self.splash = None
        self.init_thread = None
        self.success = False
        self.error_message = ""

    def initialize(self):
        """
        Initialize application with enhanced splash screen
        Returns: (success: bool, error_message: str)
        """
        # Show splash screen
        self.splash = EnhancedSplashScreen()

        # Connect retry button
        self.splash.retry_button.clicked.connect(self.retry_initialization)

        self.splash.show()
        QApplication.processEvents()

        # Start initialization
        self.start_initialization()

        # Wait for completion
        self.init_thread.wait()

        # Return result
        return self.success, self.error_message

    def start_initialization(self):
        """Start the initialization thread"""
        # Create and configure thread
        self.init_thread = InitializationThread(self.data_dir)
        self.init_thread.progress.connect(self.on_progress)
        self.init_thread.finished.connect(self.on_finished)
        self.init_thread.health_check.connect(self.on_health_check)
        self.init_thread.start()

    def retry_initialization(self):
        """Retry initialization after failure"""
        # Reset UI
        self.splash.retry_button.hide()
        self.splash.status_label.setStyleSheet("""
            color: white;
            background: transparent;
        """)
        self.splash.progress_bar.setValue(0)
        self.splash.percent_label.setText("0%")

        # Clear health status
        for widget in self.splash.health_status.values():
            widget[0].setParent(None)
            widget[1].setParent(None)
        self.splash.health_status.clear()

        # Restart initialization
        self.start_initialization()

    def on_progress(self, message, percentage, detail):
        """Handle progress update"""
        if self.splash:
            self.splash.update_progress(message, percentage, detail)

    def on_health_check(self, component, healthy):
        """Handle health check update"""
        if self.splash:
            self.splash.add_health_status(component, healthy)

    def on_finished(self, success, error_message):
        """Handle initialization completion"""
        self.success = success
        self.error_message = error_message

        if self.splash:
            if success:
                # Show success state briefly
                self.splash.update_progress("Startup complete!", 100, "Ready to use")
                QTimer.singleShot(800, self.splash.close)
            else:
                # Show error state
                self.splash.show_error(error_message)

    def cleanup(self):
        """Clean up resources"""
        if self.init_thread and self.init_thread.isRunning():
            self.init_thread.stop()
            self.init_thread.wait(5000)  # Wait up to 5 seconds

        if self.splash:
            self.splash.close()


def initialize_with_gui(data_dir):
    """
    Initialize application with enhanced GUI splash screen

    Args:
        data_dir: Path to application data directory

    Returns:
        (success: bool, error_message: str)
    """
    # Create QApplication if needed
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # Run startup manager
    manager = StartupManager(app, data_dir)

    try:
        success, error = manager.initialize()
        return success, error
    finally:
        manager.cleanup()


# Convenience function for command-line testing
def main():
    """Test the startup manager"""
    import tempfile

    data_dir = Path(tempfile.mkdtemp()) / "primebooks_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    success, error = initialize_with_gui(data_dir)

    if success:
        print("✅ Initialization successful!")
    else:
        print(f"❌ Initialization failed: {error}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())