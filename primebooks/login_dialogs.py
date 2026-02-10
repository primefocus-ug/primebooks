# primebooks/login_dialogs.py
"""
Login Dialogs for PrimeBooks Desktop
✅ Initial login (subdomain + credentials)
✅ User switching (same company, different user)
✅ Subscription validation
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# INITIAL LOGIN DIALOG (Subdomain + Email + Password)
# ============================================================================

class InitialLoginDialog(QDialog):
    """
    Initial login dialog - First time app opens
    ✅ Asks for subdomain, email, password
    ✅ Authenticates with cloud
    ✅ Downloads company data
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PrimeBooks - Login")
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
        self.subdomain_input.setStyleSheet(self._get_input_style())
        layout.addWidget(self.subdomain_input)
        layout.addSpacing(10)

        # Email input
        email_label = QLabel("Email:")
        email_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your@email.com")
        self.email_input.setStyleSheet(self._get_input_style())
        layout.addWidget(self.email_input)
        layout.addSpacing(10)

        # Password input
        password_label = QLabel("Password:")
        password_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setStyleSheet(self._get_input_style())
        self.password_input.returnPressed.connect(self.handle_login)
        layout.addWidget(self.password_input)
        layout.addSpacing(20)

        # Login button
        self.login_btn = QPushButton("Login & Sync Data")
        self.login_btn.setStyleSheet(self._get_button_style())
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
        """Handle initial login"""
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

        # Start login
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

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(500, self.accept)
        else:
            self.show_error(message)

    def show_error(self, message):
        """Show error message"""
        self.status_label.setText(f"✗ {message}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    def _get_input_style(self):
        return """
            QLineEdit {
                padding: 8px;
                border: 2px solid #bdc3c7;
                border-radius: 4px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
            }
        """

    def _get_button_style(self):
        return """
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
        """


# ============================================================================
# USER SWITCHING DIALOG (Email + Password only)
# ============================================================================

class UserSwitchDialog(QDialog):
    """
    User switching dialog - Switch user without closing app
    ✅ Only asks for email + password (subdomain already known)
    ✅ Validates subscription
    ✅ Allows offline login with grace period
    """

    def __init__(self, company_schema, company_id, parent=None):
        super().__init__(parent)
        self.company_schema = company_schema
        self.company_id = company_id

        self.setWindowTitle(f"Switch User - {company_schema}")
        self.setFixedWidth(400)
        self.setModal(True)

        self.auth_token = None
        self.user_data = None

        self.setup_ui()

        # Check subscription on open
        self.check_subscription()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h3>Switch User</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #2c3e50; margin: 10px 0;")
        layout.addWidget(title)

        company_label = QLabel(f"<b>Company:</b> {self.company_schema}")
        company_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        company_label.setStyleSheet("color: #7f8c8d; margin-bottom: 20px;")
        layout.addWidget(company_label)

        # Email input
        email_label = QLabel("Email:")
        email_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your@email.com")
        self.email_input.setStyleSheet(self._get_input_style())
        layout.addWidget(self.email_input)
        layout.addSpacing(10)

        # Password input
        password_label = QLabel("Password:")
        password_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setStyleSheet(self._get_input_style())
        self.password_input.returnPressed.connect(self.handle_login)
        layout.addWidget(self.password_input)
        layout.addSpacing(10)

        # Subscription status label
        self.subscription_label = QLabel("")
        self.subscription_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subscription_label.setWordWrap(True)
        layout.addWidget(self.subscription_label)
        layout.addSpacing(10)

        # Buttons
        btn_layout = QHBoxLayout()

        self.login_btn = QPushButton("Login")
        self.login_btn.setStyleSheet(self._get_button_style())
        self.login_btn.clicked.connect(self.handle_login)
        btn_layout.addWidget(self.login_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #e74c3c; margin-top: 10px;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def check_subscription(self):
        """Check subscription status on dialog open"""
        try:
            from primebooks.subscription import SubscriptionManager

            sub_manager = SubscriptionManager(self.company_id, self.company_schema)
            is_valid, message, days, status = sub_manager.validate_subscription()

            if not is_valid:
                # Subscription invalid - disable login
                self.subscription_label.setText(f"⛔ {message}")
                self.subscription_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.login_btn.setEnabled(False)
            elif days <= 7:
                # Subscription expiring soon or in grace period
                if status == 'GRACE_PERIOD':
                    self.subscription_label.setText(f"⚠️ {message}")
                    self.subscription_label.setStyleSheet("color: #e67e22; font-weight: bold;")
                else:
                    self.subscription_label.setText(f"⚠️ {message}")
                    self.subscription_label.setStyleSheet("color: #f39c12;")
            else:
                # All good
                self.subscription_label.setText(f"✓ {message}")
                self.subscription_label.setStyleSheet("color: #27ae60;")

        except Exception as e:
            logger.error(f"Failed to check subscription: {e}")
            # Don't block login on error

    def handle_login(self):
        """Handle user switch login"""
        email = self.email_input.text().strip()
        password = self.password_input.text()

        if not email:
            self.show_error("Please enter your email")
            return

        if not password:
            self.show_error("Please enter your password")
            return

        # Disable button
        self.login_btn.setEnabled(False)
        self.status_label.setText("Authenticating...")
        self.status_label.setStyleSheet("color: #3498db;")

        # Try local authentication first (fast!)
        success, result = self.authenticate_locally(email, password)

        if success:
            self.auth_token = result.get('token')
            self.user_data = result.get('user')

            self.status_label.setText("✓ Login successful!")
            self.status_label.setStyleSheet("color: #27ae60;")

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self.accept)
            return

        # Local auth failed - try cloud if online
        self.status_label.setText("Verifying with server...")
        success, result = self.authenticate_cloud(email, password)

        if success:
            self.auth_token = result.get('token')
            self.user_data = result.get('user')

            self.status_label.setText("✓ Login successful!")
            self.status_label.setStyleSheet("color: #27ae60;")

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self.accept)
        else:
            self.login_btn.setEnabled(True)
            self.show_error(result.get('error', 'Authentication failed'))

    def authenticate_locally(self, email, password):
        """Authenticate against local database"""
        try:
            from django_tenants.utils import schema_context
            from accounts.models import CustomUser

            with schema_context(self.company_schema):
                user = CustomUser.objects.get(email=email)

                # Check if user is active
                if not user.is_active:
                    return False, {'error': 'User account is inactive'}

                # Verify password
                if user.check_password(password):
                    logger.info(f"✅ Local authentication successful: {email}")
                    return True, {
                        'token': 'local_session',  # Use existing token
                        'user': {
                            'id': user.id,
                            'email': user.email,
                            'username': user.username,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                        }
                    }
                else:
                    return False, {'error': 'Invalid password'}

        except Exception as e:
            logger.debug(f"Local authentication failed: {e}")
            return False, {'error': 'User not found locally'}

    def authenticate_cloud(self, email, password):
        """Authenticate with cloud server"""
        try:
            from primebooks.auth import DesktopAuthManager
            import requests
            from django.conf import settings

            auth_manager = DesktopAuthManager()

            # Check if online
            try:
                requests.get('https://www.google.com', timeout=3)
            except:
                return False, {'error': 'Server not reachable. Working offline.'}

            # Build URL
            is_development = settings.DEBUG or auth_manager.base_domain == 'localhost'

            if is_development:
                url = f"http://{self.company_schema}.localhost:8000/api/desktop/auth/login/"
            else:
                url = f"https://{self.company_schema}.{auth_manager.base_domain}/api/desktop/auth/login/"

            # Authenticate
            response = requests.post(
                url,
                json={'email': email, 'password': password},
                timeout=10,
                verify=not is_development
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Cloud authentication successful: {email}")
                return True, {
                    'token': data.get('token'),
                    'user': data.get('user')
                }
            else:
                return False, {'error': 'Invalid credentials'}

        except Exception as e:
            logger.error(f"Cloud authentication error: {e}")
            return False, {'error': 'Server error'}

    def show_error(self, message):
        """Show error message"""
        self.status_label.setText(f"✗ {message}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    def _get_input_style(self):
        return """
            QLineEdit {
                padding: 8px;
                border: 2px solid #bdc3c7;
                border-radius: 4px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
            }
        """

    def _get_button_style(self):
        return """
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """


# ============================================================================
# LOGIN THREAD (Background authentication)
# ============================================================================

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