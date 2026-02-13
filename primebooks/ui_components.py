#!/usr/bin/env python
"""
PrimeBooks Desktop - IMPROVED UI WITH BETTER PROGRESS FEEDBACK
✅ Modern splash screen with detailed progress
✅ Enhanced login dialog with better UX
✅ Real-time sync progress with visual feedback
✅ Status indicators and notifications
✅ Smooth animations and transitions
"""

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QProgressBar, QWidget, QFrame,
    QGraphicsDropShadowEffect, QTextEdit, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QPainter, QLinearGradient


# ============================================================================
# MODERN SPLASH SCREEN WITH PROGRESS
# ============================================================================

class ModernSplashScreen(QDialog):
    """
    Modern splash screen with detailed progress tracking
    ✅ Shows logo/branding
    ✅ Animated progress bar
    ✅ Step-by-step status updates
    ✅ Estimated time remaining
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(500, 400)

        self.steps = []
        self.current_step = 0
        self.start_time = None

        self.setup_ui()
        self.center_on_screen()

    def setup_ui(self):
        """Setup the splash screen UI"""
        # Main container
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Content frame with rounded corners and shadow
        self.content_frame = QFrame()
        self.content_frame.setObjectName("contentFrame")
        self.content_frame.setStyleSheet("""
            #contentFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea,
                    stop:1 #764ba2
                );
                border-radius: 20px;
            }
        """)

        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 10)
        self.content_frame.setGraphicsEffect(shadow)

        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(20)

        # Logo/Title
        title_label = QLabel("PrimeBooks")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 36px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
            }
        """)
        content_layout.addWidget(title_label)

        subtitle_label = QLabel("Desktop Edition")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.8);
                font-size: 14px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        content_layout.addWidget(subtitle_label)

        content_layout.addSpacing(20)

        # Status message
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                font-family: 'Segoe UI', Arial;
                min-height: 40px;
            }
        """)
        content_layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 0.2);
            }
            QProgressBar::chunk {
                border-radius: 4px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #fff,
                    stop:1 rgba(255, 255, 255, 0.8)
                );
            }
        """)
        content_layout.addWidget(self.progress_bar)

        # Percentage label
        self.percent_label = QLabel("0%")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.percent_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.9);
                font-size: 12px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        content_layout.addWidget(self.percent_label)

        # Steps list (scrollable)
        self.steps_scroll = QScrollArea()
        self.steps_scroll.setWidgetResizable(True)
        self.steps_scroll.setFixedHeight(120)
        self.steps_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(255, 255, 255, 0.1);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.3);
                border-radius: 3px;
            }
        """)

        self.steps_widget = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_widget)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(5)
        self.steps_scroll.setWidget(self.steps_widget)

        content_layout.addWidget(self.steps_scroll)

        # Time estimate
        self.time_label = QLabel("Estimated time: Calculating...")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.7);
                font-size: 11px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        content_layout.addWidget(self.time_label)

        main_layout.addWidget(self.content_frame)
        self.setLayout(main_layout)

    def update_progress(self, message, percentage):
        """Update progress with animation"""
        self.status_label.setText(message)

        # Animate progress bar
        self.animate_progress(percentage)

        # Update percentage
        self.percent_label.setText(f"{percentage}%")

        # Add to steps list
        self.add_step(message, percentage == 100)

        # Update time estimate
        self.update_time_estimate(percentage)

    def animate_progress(self, target_value):
        """Animate progress bar smoothly"""
        self.animation = QPropertyAnimation(self.progress_bar, b"value")
        self.animation.setDuration(300)
        self.animation.setStartValue(self.progress_bar.value())
        self.animation.setEndValue(target_value)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.start()

    def add_step(self, message, completed=False):
        """Add a step to the steps list"""
        step_label = QLabel()

        if completed:
            icon = "✅"
            color = "rgba(255, 255, 255, 0.9)"
        elif message == self.status_label.text():
            icon = "⏳"
            color = "white"
        else:
            icon = "⏸️"
            color = "rgba(255, 255, 255, 0.5)"

        step_label.setText(f"{icon} {message}")
        step_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 11px;
                font-family: 'Segoe UI', Arial;
                padding: 3px;
            }}
        """)

        self.steps_layout.addWidget(step_label)
        self.steps.append(step_label)

        # Auto-scroll to bottom
        QTimer.singleShot(50, lambda: self.steps_scroll.verticalScrollBar().setValue(
            self.steps_scroll.verticalScrollBar().maximum()
        ))

    def update_time_estimate(self, percentage):
        """Update estimated time remaining"""
        import time

        if self.start_time is None:
            self.start_time = time.time()

        if percentage > 0:
            elapsed = time.time() - self.start_time
            total_estimated = (elapsed / percentage) * 100
            remaining = total_estimated - elapsed

            if remaining < 60:
                time_str = f"{int(remaining)} seconds"
            else:
                time_str = f"{int(remaining / 60)} minutes"

            self.time_label.setText(f"Estimated time remaining: {time_str}")

    def center_on_screen(self):
        """Center the dialog on screen"""
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)


# ============================================================================
# ENHANCED LOGIN DIALOG
# ============================================================================

class EnhancedLoginDialog(QDialog):
    """
    Modern login dialog with better UX
    ✅ Clean, modern design
    ✅ Input validation feedback
    ✅ Loading states
    ✅ Error messages with icons
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login to PrimeBooks")
        self.setFixedSize(450, 550)
        self.setStyleSheet("""
            QDialog {
                background: #f5f7fa;
            }
        """)

        self.auth_token = None
        self.user_data = None
        self.company_data = None

        self.setup_ui()

    def setup_ui(self):
        """Setup enhanced login UI"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Header section with gradient
        header = QFrame()
        header.setFixedHeight(120)
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea,
                    stop:1 #764ba2
                );
                border-radius: 0;
            }
        """)

        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(30, 20, 30, 20)

        title = QLabel("Welcome Back")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
            }
        """)
        header_layout.addWidget(title)

        subtitle = QLabel("Login to access your business data")
        subtitle.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.9);
                font-size: 13px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        header_layout.addWidget(subtitle)

        main_layout.addWidget(header)

        # Form section
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setContentsMargins(30, 30, 30, 30)
        form_layout.setSpacing(20)

        # Subdomain input
        subdomain_label = QLabel("Company Subdomain")
        subdomain_label.setStyleSheet("""
            QLabel {
                color: #2d3748;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', Arial;
            }
        """)
        form_layout.addWidget(subdomain_label)

        self.subdomain_input = QLineEdit()
        self.subdomain_input.setPlaceholderText("e.g., mycompany")
        self.subdomain_input.setStyleSheet(self._input_style())
        form_layout.addWidget(self.subdomain_input)

        # Email input
        email_label = QLabel("Email Address")
        email_label.setStyleSheet(subdomain_label.styleSheet())
        form_layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your.email@company.com")
        self.email_input.setStyleSheet(self._input_style())
        form_layout.addWidget(self.email_input)

        # Password input
        password_label = QLabel("Password")
        password_label.setStyleSheet(subdomain_label.styleSheet())
        form_layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setStyleSheet(self._input_style())
        self.password_input.returnPressed.connect(self.handle_login)
        form_layout.addWidget(self.password_input)

        # Status/Error message area
        self.status_container = QFrame()
        self.status_container.setFixedHeight(60)
        self.status_container.hide()

        status_layout = QHBoxLayout(self.status_container)
        status_layout.setContentsMargins(15, 10, 15, 10)

        self.status_icon = QLabel("ℹ️")
        self.status_icon.setStyleSheet("font-size: 20px;")
        status_layout.addWidget(self.status_icon)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #2d3748;
                font-size: 12px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        status_layout.addWidget(self.status_label, 1)

        form_layout.addWidget(self.status_container)

        # Login button
        self.login_btn = QPushButton("Login")
        self.login_btn.setFixedHeight(45)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea,
                    stop:1 #764ba2
                );
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
                font-family: 'Segoe UI', Arial;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5568d3,
                    stop:1 #6a3f8f
                );
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4c5bc4,
                    stop:1 #5d3680
                );
            }
            QPushButton:disabled {
                background: #cbd5e0;
            }
        """)
        self.login_btn.clicked.connect(self.handle_login)
        form_layout.addWidget(self.login_btn)

        # Progress indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea,
                    stop:1 #764ba2
                );
            }
        """)
        self.progress_bar.hide()
        form_layout.addWidget(self.progress_bar)

        form_layout.addStretch()

        main_layout.addWidget(form_container)
        self.setLayout(main_layout)

    def _input_style(self):
        """Common input field style"""
        return """
            QLineEdit {
                padding: 12px 15px;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                font-size: 14px;
                font-family: 'Segoe UI', Arial;
                background: white;
                color: #2d3748;
            }
            QLineEdit:focus {
                border: 2px solid #667eea;
                outline: none;
            }
            QLineEdit::placeholder {
                color: #a0aec0;
            }
        """

    def handle_login(self):
        """Handle login with validation"""
        subdomain = self.subdomain_input.text().strip()
        email = self.email_input.text().strip()
        password = self.password_input.text()

        # Validate inputs
        if not subdomain:
            self.show_status("error", "Please enter your company subdomain")
            self.subdomain_input.setFocus()
            return

        if not email:
            self.show_status("error", "Please enter your email address")
            self.email_input.setFocus()
            return

        if not password:
            self.show_status("error", "Please enter your password")
            self.password_input.setFocus()
            return

        # Start login
        self.login_btn.setEnabled(False)
        self.login_btn.setText("Logging in...")
        self.progress_bar.show()
        self.show_status("info", "Connecting to server...")

        # TODO: Start login thread
        # self.login_thread = LoginThread(subdomain, email, password)
        # self.login_thread.start()

    def show_status(self, status_type, message):
        """Show status message with appropriate styling"""
        self.status_container.show()

        if status_type == "error":
            self.status_icon.setText("❌")
            self.status_container.setStyleSheet("""
                QFrame {
                    background: #fed7d7;
                    border-left: 4px solid #f56565;
                    border-radius: 6px;
                }
            """)
        elif status_type == "success":
            self.status_icon.setText("✅")
            self.status_container.setStyleSheet("""
                QFrame {
                    background: #c6f6d5;
                    border-left: 4px solid #48bb78;
                    border-radius: 6px;
                }
            """)
        elif status_type == "info":
            self.status_icon.setText("ℹ️")
            self.status_container.setStyleSheet("""
                QFrame {
                    background: #bee3f8;
                    border-left: 4px solid #4299e1;
                    border-radius: 6px;
                }
            """)

        self.status_label.setText(message)


# ============================================================================
# MODERN SYNC PROGRESS DIALOG
# ============================================================================

class ModernSyncDialog(QDialog):
    """
    Modern sync dialog with detailed progress
    ✅ Shows current operation
    ✅ Data transfer stats
    ✅ Success/failure indicators
    ✅ Detailed logs
    """

    def __init__(self, subdomain, token, company_data):
        super().__init__()
        self.subdomain = subdomain
        self.token = token
        self.company_data = company_data

        self.setWindowTitle("Syncing Your Data")
        self.setFixedSize(600, 500)
        self.setModal(True)

        self.records_downloaded = 0
        self.models_synced = 0

        self.setup_ui()
        QTimer.singleShot(100, self.start_sync)

    def setup_ui(self):
        """Setup modern sync UI"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QFrame()
        header.setFixedHeight(80)
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea,
                    stop:1 #764ba2
                );
            }
        """)

        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(30, 15, 30, 15)

        title = QLabel("📥 Syncing Your Data")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 24px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
            }
        """)
        header_layout.addWidget(title)

        subtitle = QLabel("Downloading your business data from the cloud")
        subtitle.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.9);
                font-size: 13px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        header_layout.addWidget(subtitle)

        main_layout.addWidget(header)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.setSpacing(20)

        # Current operation
        self.operation_label = QLabel("Preparing to sync...")
        self.operation_label.setStyleSheet("""
            QLabel {
                color: #2d3748;
                font-size: 15px;
                font-weight: 600;
                font-family: 'Segoe UI', Arial;
            }
        """)
        content_layout.addWidget(self.operation_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 6px;
                background: #e2e8f0;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea,
                    stop:1 #764ba2
                );
            }
        """)
        content_layout.addWidget(self.progress_bar)

        # Stats row
        stats_container = QFrame()
        stats_container.setStyleSheet("""
            QFrame {
                background: #f7fafc;
                border-radius: 10px;
                padding: 15px;
            }
        """)

        stats_layout = QHBoxLayout(stats_container)
        stats_layout.setSpacing(30)

        # Records stat
        records_widget = QWidget()
        records_layout = QVBoxLayout(records_widget)
        records_layout.setContentsMargins(0, 0, 0, 0)
        records_layout.setSpacing(5)

        self.records_value = QLabel("0")
        self.records_value.setStyleSheet("""
            QLabel {
                color: #667eea;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
            }
        """)
        records_layout.addWidget(self.records_value)

        records_label = QLabel("Records")
        records_label.setStyleSheet("""
            QLabel {
                color: #718096;
                font-size: 12px;
                font-family: 'Segoe UI', Arial;
            }
        """)
        records_layout.addWidget(records_label)

        stats_layout.addWidget(records_widget)

        # Models stat
        models_widget = QWidget()
        models_layout = QVBoxLayout(models_widget)
        models_layout.setContentsMargins(0, 0, 0, 0)
        models_layout.setSpacing(5)

        self.models_value = QLabel("0")
        self.models_value.setStyleSheet(self.records_value.styleSheet())
        models_layout.addWidget(self.models_value)

        models_label = QLabel("Models")
        models_label.setStyleSheet(records_label.styleSheet())
        models_layout.addWidget(models_label)

        stats_layout.addWidget(models_widget)

        # Speed stat
        speed_widget = QWidget()
        speed_layout = QVBoxLayout(speed_widget)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.setSpacing(5)

        self.speed_value = QLabel("--")
        self.speed_value.setStyleSheet(self.records_value.styleSheet())
        speed_layout.addWidget(self.speed_value)

        speed_label = QLabel("Records/sec")
        speed_label.setStyleSheet(records_label.styleSheet())
        speed_layout.addWidget(speed_label)

        stats_layout.addWidget(speed_widget)

        content_layout.addWidget(stats_container)

        # Activity log
        log_label = QLabel("Activity Log")
        log_label.setStyleSheet("""
            QLabel {
                color: #4a5568;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', Arial;
            }
        """)
        content_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background: white;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                color: #2d3748;
            }
        """)
        content_layout.addWidget(self.log_text)

        main_layout.addWidget(content)
        self.setLayout(main_layout)

    def start_sync(self):
        """Start the sync process"""
        # TODO: Start sync thread
        self.update_progress("Connecting to server...", 10)
        self.add_log("🔌 Establishing connection...")

    def update_progress(self, message, percentage):
        """Update sync progress"""
        self.operation_label.setText(message)
        self.progress_bar.setValue(percentage)

    def add_log(self, message):
        """Add message to activity log"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_stats(self, records, models, speed=None):
        """Update statistics"""
        self.records_downloaded = records
        self.models_synced = models

        self.records_value.setText(str(records))
        self.models_value.setText(str(models))

        if speed:
            self.speed_value.setText(f"{speed:.1f}")


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == '__main__':
    import sys

    app = QApplication(sys.argv)

    # Show splash screen
    splash = ModernSplashScreen()
    splash.show()


    # Simulate progress updates
    def update_splash():
        progress = 0
        steps = [
            (10, "Initializing application..."),
            (25, "Loading PostgreSQL..."),
            (40, "Setting up database..."),
            (60, "Loading Django..."),
            (80, "Preparing user interface..."),
            (100, "Ready!"),
        ]

        for percentage, message in steps:
            QTimer.singleShot(percentage * 50,
                              lambda p=percentage, m=message: splash.update_progress(m, p))


    update_splash()


    # Show login after splash
    def show_login():
        splash.close()
        login = EnhancedLoginDialog()
        login.exec()


    QTimer.singleShot(7000, show_login)

    sys.exit(app.exec())