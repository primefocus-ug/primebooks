from pathlib import Path
from datetime import timedelta
from django.utils.translation import gettext_lazy as _
import os
import sys

try:
    from celery.schedules import crontab

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    crontab = None

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
from dotenv import load_dotenv

env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path, override=True)


# =============================================================================
# PRODUCTION DETECTION
# =============================================================================

def is_compiled():
    """
    Detect if running as compiled executable (PyInstaller or Nuitka)

    Returns:
        bool: True if compiled, False if running as Python script
    """
    # Method 1: PyInstaller sets sys.frozen
    if getattr(sys, 'frozen', False):
        return True

    # Method 2: Nuitka sets __compiled__
    if '__compiled__' in globals():
        return True

    # Method 3: Check if _MEIPASS exists (PyInstaller temp folder)
    if hasattr(sys, '_MEIPASS'):
        return True

    return False


# =============================================================================
# DEPLOYMENT MODE DETECTION
# =============================================================================

# Detect deployment mode
IS_DESKTOP = os.getenv('DESKTOP_MODE', 'False').lower() == 'true'
IS_COMPILED = is_compiled()

# Debug mode logic:
# - If compiled (exe) → Production (DEBUG=False)
# - If not compiled (python script) → Use environment variable
if IS_COMPILED:
    DEBUG = False  # Always production when compiled
    IS_PRODUCTION = True
else:
    # Running as python script - use environment variable
    DEBUG_VALUE = os.getenv('DEBUG', 'True')
    DEBUG = DEBUG_VALUE.strip().lower() in ('true', '1', 'yes', 'on')
    IS_PRODUCTION = False

# Base domain for sync
if IS_COMPILED:
    # Production - compiled executable
    BASE_DOMAIN = 'primebooks.sale'
    PROTOCOL = 'https'
else:
    # Development - python script
    BASE_DOMAIN = os.getenv('BASE_DOMAIN', 'localhost:8000')
    PROTOCOL = 'http'

# Log the mode for debugging
print("=" * 60)
print(f"🔍 Environment Detection")
print("=" * 60)
print(f"Is Compiled: {IS_COMPILED}")
print(f"Is Desktop: {IS_DESKTOP}")
print(f"Is Production: {IS_PRODUCTION}")
print(f"DEBUG: {DEBUG}")
print(f"Base Domain: {BASE_DOMAIN}")
print(f"Protocol: {PROTOCOL}")
print("=" * 60)

if IS_DESKTOP:
    # Prevent Celery-related imports in desktop mode
    import sys
    from unittest.mock import MagicMock

    # Mock Celery modules
    sys.modules['celery'] = MagicMock()
    sys.modules['celery.schedules'] = MagicMock()
    sys.modules['celery.result'] = MagicMock()
    sys.modules['kombu'] = MagicMock()


# Helper function for desktop data directory
def get_desktop_data_dir():
    """Get appropriate data directory for desktop mode"""
    if not IS_DESKTOP:
        return BASE_DIR

    if os.name == 'nt':  # Windows
        data_dir = Path(os.environ.get('APPDATA', '')) / 'PrimeBooks'
    elif sys.platform == 'darwin':  # macOS
        data_dir = Path.home() / 'Library' / 'Application Support' / 'PrimeBooks'
    else:  # Linux
        data_dir = Path.home() / '.local' / 'share' / 'PrimeBooks'

    # Create directory if it doesn't exist
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


# Desktop data directory
DESKTOP_DATA_DIR = get_desktop_data_dir()

import pytz
from datetime import datetime

# Timezone — defined early so the maintenance block and Celery config below
# can both reference it. The Internationalization section further down uses
# this same value; do not add a second assignment there.
TIME_ZONE = os.getenv('TIME_ZONE', 'Africa/Kampala')
USE_TZ = True

# Maintenance settings
MAINTENANCE_ACTIVE = os.getenv("MAINTENANCE_ACTIVE", "False").lower() == "true"
MAINTENANCE_MESSAGE = os.getenv("MAINTENANCE_MESSAGE", "System maintenance scheduled.")

# Convert string to timezone-aware datetime
maintenance_time_str = os.getenv("MAINTENANCE_START_TIME", None)
if maintenance_time_str:
    tz = pytz.timezone(TIME_ZONE)
    MAINTENANCE_START_TIME = tz.localize(datetime.strptime(maintenance_time_str, "%Y-%m-%d %H:%M:%S"))
else:
    MAINTENANCE_START_TIME = None

# =============================================================================
# MODE-SPECIFIC CONFIGURATION
# =============================================================================
REST_FRAMEWORK_THROTTLE_RATES = {
    'user': '1000/day',
    'anon': '100/day',
}

if IS_DESKTOP:
    # =========================================================================
    # DESKTOP MODE - PostgreSQL with schema-per-tenant
    # =========================================================================
    print("=" * 50)
    print("💻 RUNNING IN DESKTOP MODE (PostgreSQL)")
    print(f"📁 Data Directory: {DESKTOP_DATA_DIR}")
    if IS_COMPILED:
        print("🚀 Desktop Production Mode (Compiled)")
    else:
        print("🔧 Desktop Development Mode (Python Script)")
    print("=" * 50)

    # Secret key - generate unique per installation
    SECRET_KEY_FILE = DESKTOP_DATA_DIR / '.secret_key'
    if not SECRET_KEY_FILE.exists():
        from django.core.management.utils import get_random_secret_key

        SECRET_KEY_FILE.write_text(get_random_secret_key())
    SECRET_KEY = SECRET_KEY_FILE.read_text().strip()

    ALLOWED_HOSTS = ['*']

    if IS_COMPILED:
        PUBLIC_ADMIN_URL = f'{PROTOCOL}://{BASE_DOMAIN}'
    else:
        PUBLIC_ADMIN_URL = 'http://localhost:8000'

    # ✅ PostgreSQL Database (embedded instance)
    DATABASES = {
        'default': {
            'ENGINE': 'django_tenants.postgresql_backend',
            'NAME': 'primebooks',
            'USER': 'primebooks_user',
            'PASSWORD': '',
            'HOST': 'localhost',
            'PORT': '5433',  # Non-standard port to avoid conflicts
        }
    }

    # ✅ Django-Tenants Configuration
    TENANT_MODEL = "company.Company"
    TENANT_DOMAIN_MODEL = "company.Domain"
    PUBLIC_SCHEMA_NAME = 'public'
    PUBLIC_SCHEMA_URLCONF = 'tenancy.public_urls'
    SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

    # Redis - Disable for desktop or use minimal config
    REDIS_URL = None
    CELERY_TASK_ALWAYS_EAGER = True  # Run tasks synchronously
    CELERY_TASK_EAGER_PROPAGATES = True

    # Email - Console backend for desktop
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    EMAIL_HOST = 'localhost'
    EMAIL_PORT = 25
    EMAIL_USE_TLS = False
    EMAIL_HOST_USER = ''
    EMAIL_HOST_PASSWORD = ''
    DEFAULT_FROM_EMAIL = 'kondenationafrica@gmail.com'
    SUPPORT_EMAIL = 'primefocusug@gmail.com'


    # Site
    if IS_COMPILED:
        FRONTEND_URL = f'{PROTOCOL}://{BASE_DOMAIN}'
        SITE_NAME = 'Prime Books'
    else:
        FRONTEND_URL = 'http://localhost:8000'
        SITE_NAME = 'Prime Books Desktop'

    USE_SSL = IS_COMPILED  # Use SSL in production (compiled)

    # CORS
    CORS_ALLOW_ALL_ORIGINS = True

    # Security - Production desktop gets stricter settings
    if IS_COMPILED:
        SECURE_BROWSER_XSS_FILTER = True
        SECURE_CONTENT_TYPE_NOSNIFF = True
        X_FRAME_OPTIONS = 'DENY'
        SECURE_HSTS_SECONDS = 0  # Desktop doesn't need HSTS
        SECURE_HSTS_INCLUDE_SUBDOMAINS = False
        SECURE_HSTS_PRELOAD = False
        SESSION_COOKIE_SECURE = False  # Desktop runs on localhost
        CSRF_COOKIE_SECURE = False
        CSRF_COOKIE_SAMESITE = 'Lax'
        SECURE_SSL_REDIRECT = False
        SECURE_PROXY_SSL_HEADER = None
        SESSION_COOKIE_AGE = 86400  # 1 day
        print(f"   Security: Production desktop mode")
    else:
        # Development desktop - relaxed security
        SECURE_BROWSER_XSS_FILTER = False
        SECURE_CONTENT_TYPE_NOSNIFF = False
        X_FRAME_OPTIONS = 'SAMEORIGIN'
        SECURE_HSTS_SECONDS = 0
        SECURE_HSTS_INCLUDE_SUBDOMAINS = False
        SECURE_HSTS_PRELOAD = False
        SESSION_COOKIE_SECURE = False
        CSRF_COOKIE_SECURE = False
        CSRF_COOKIE_SAMESITE = 'Lax'
        SECURE_SSL_REDIRECT = False
        SECURE_PROXY_SSL_HEADER = None
        SESSION_COOKIE_AGE = 86400
        print(f"   Security: Development desktop mode")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'

    # Static files
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

    # Cache - Use dummy cache for desktop
    CACHE_BACKEND = 'django.core.cache.backends.dummy.DummyCache'
    CACHE_OPTIONS = {}

    # Logging
    if IS_COMPILED:
        LOG_LEVEL = 'ERROR'
        CONSOLE_LOG_LEVEL = 'ERROR'
        print(f"   Logging: ERROR level only")
    else:
        LOG_LEVEL = 'DEBUG'
        CONSOLE_LOG_LEVEL = 'INFO'
        print(f"   Logging: DEBUG level")

    FILE_LOG_FORMATTER = 'simple'
    MAX_LOG_BYTES = 5 * 1024 * 1024
    LOG_BACKUP_COUNT = 3
    LOG_DIR = DESKTOP_DATA_DIR / 'logs'

    # Media files - Store in desktop data directory
    MEDIA_ROOT = DESKTOP_DATA_DIR / 'media'

    # Disable WebSocket for desktop
    WEBSOCKET_ALLOWED_ORIGINS = ['http://localhost:8000']

    # ✅ Database routing - django-tenants ONLY
    DATABASE_ROUTERS = ['django_tenants.routers.TenantSyncRouter']

    # Sync configuration - auto-detect based on compilation
    if IS_COMPILED:
        # Production desktop - sync will use: https://{tenant}.primebooks.sale
        print(f"   Sync: https://{{tenant}}.{BASE_DOMAIN}")
    else:
        # Development desktop - sync will use: http://{tenant}.localhost:8000
        print(f"   Sync: http://{{tenant}}.{BASE_DOMAIN}")

    # Update server for version checks
    if IS_COMPILED:
        UPDATE_SERVER_URL = f'{PROTOCOL}://{BASE_DOMAIN}/api/version/latest/'
    else:
        UPDATE_SERVER_URL = 'http://localhost:8000/api/version/latest/'

elif DEBUG:
    # =========================================================================
    # DEVELOPMENT MODE (WEB) - Uses hardcoded values
    # =========================================================================
    print("=" * 50)
    print("🔧 RUNNING IN WEB DEVELOPMENT MODE")
    print("=" * 50)

    SECRET_KEY = 'django-insecure-9mghr4buf3l(sinf2(lez20c&*=2)lha_qkdyrxeu1#14@p&(%'
    ALLOWED_HOSTS = ['*']
    PUBLIC_ADMIN_URL = 'http://localhost:8000'
    BASE_DOMAINS='localhost'
    # Database - PostgreSQL with schema-per-tenant
    DATABASES = {
        'default': {
            'ENGINE': 'django_tenants.postgresql_backend',
            'NAME': 'data',
            'USER': 'postgres',
            'PASSWORD': '@Developer25',
            'HOST': 'localhost',
            'PORT': '5432',
        }
    }

    # Redis
    REDIS_URL = 'redis://127.0.0.1:6379'

    # Email
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    EMAIL_HOST = 'localhost'
    EMAIL_PORT = 25
    EMAIL_USE_TLS = False
    EMAIL_HOST_USER = ''
    EMAIL_HOST_PASSWORD = ''
    DEFAULT_FROM_EMAIL = 'kondenationafrica@gmail.com'
    SUPPORT_EMAIL = 'primefocusug@gmail.com'

    # Site
    FRONTEND_URL = 'http://localhost:8000'
    SITE_NAME = 'Prime Books'
    USE_SSL = os.getenv('USE_SSL', 'False').lower() in ('true', '1', 'yes')

    # CORS
    CORS_ALLOW_ALL_ORIGINS = True

    # Security - Disabled for development
    SECURE_BROWSER_XSS_FILTER = False
    SECURE_CONTENT_TYPE_NOSNIFF = False
    X_FRAME_OPTIONS = 'SAMEORIGIN'
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    CSRF_COOKIE_SAMESITE = 'Lax'
    SECURE_SSL_REDIRECT = False
    SECURE_PROXY_SSL_HEADER = None

    # Static files
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

    # Sessions
    SESSION_COOKIE_AGE = 86400
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
    TENANT_SIGNUP_URL = 'http://localhost:8000/prime-books/signup/'
    # Celery
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

    # REST Framework
    REST_FRAMEWORK_THROTTLE_RATES = {
        'user': '1000/day',
        'anon': '100/day',
    }

    # Logging
    LOG_LEVEL = 'DEBUG'
    CONSOLE_LOG_LEVEL = 'DEBUG'
    FILE_LOG_FORMATTER = 'simple'
    MAX_LOG_BYTES = 5 * 1024 * 1024
    LOG_BACKUP_COUNT = 3
    LOG_DIR = BASE_DIR / 'logs'

    # Cache settings
    CACHE_OPTIONS = {}
    CACHE_BACKEND = 'django_redis.cache.RedisCache'

    # Media
    MEDIA_ROOT = BASE_DIR / 'media'

    # Celery beat schedule intervals
    ANALYTICS_UPDATE_INTERVAL = 60.0

    # WebSocket
    WEBSOCKET_ALLOWED_ORIGINS = ['http://localhost:8000']

    # Database routing
    DATABASE_ROUTERS = ['django_tenants.routers.TenantSyncRouter']

else:
    # =========================================================================
    # PRODUCTION MODE (WEB) - Loads from .env
    # =========================================================================
    print("=" * 50)
    print("🚀 RUNNING IN WEB PRODUCTION MODE")
    print("=" * 50)

    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set in production")

    ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'primebooks.sale').split(',')]
    PUBLIC_ADMIN_URL = 'https://primebooks.sale'
    BASE_DOMAINS='primebooks.sale'
    TENANT_SIGNUP_URL = 'https://primebooks.sale/prime-books/signup/'
    # Database - PostgreSQL with schema-per-tenant
    DATABASES = {
        'default': {
            'ENGINE': 'django_tenants.postgresql_backend',
            'NAME': os.getenv('DB_NAME'),
            'USER': os.getenv('DB_USER'),
            'PASSWORD': os.getenv('DB_PASSWORD'),
            'HOST': os.getenv('DB_HOST'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
            'OPTIONS': {
                'connect_timeout': 10,
                'sslmode': os.getenv('DB_SSLMODE', 'require'),
                'application_name': 'primebooks_sales',  # visible in pg_stat_activity
            }
        }
    }

    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

    # Email
    EMAIL_BACKEND = 'company.email.TenantAwareEmailBackend'
    EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'kondenationafrica@gmail.com')
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'primefocusug@gmail.com')

    # Site
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://primebooks.sale')
    SITE_NAME = os.getenv('SITE_NAME', 'Prime Books')
    USE_SSL = os.getenv('USE_SSL', 'True').lower() in ('true', '1', 'yes')

    # CORS
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [h.strip() for h in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if h.strip()]
    CORS_ALLOW_CREDENTIALS = True

    # Security
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if h.strip()]

    # Static files — CompressedManifest adds content-hash fingerprinting so
    # browsers can cache assets with immutable headers forever.
    # Run `python manage.py collectstatic` after deploying.
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

    # Sessions
    SESSION_COOKIE_AGE = 1209600
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Lax'
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'

    # Celery
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_TASK_EAGER_PROPAGATES = False
    # Reliability: only ack a task after it completes successfully;
    # re-queue it if the worker process dies mid-execution.
    CELERY_TASK_ACKS_LATE = True
    CELERY_TASK_REJECT_ON_WORKER_LOST = True

    # REST Framework
    REST_FRAMEWORK_THROTTLE_RATES = {
        'user': '5000/day',
        'anon': '500/day',
    }

    # Logging
    LOG_LEVEL = 'INFO'
    CONSOLE_LOG_LEVEL = 'WARNING'
    FILE_LOG_FORMATTER = 'json'
    MAX_LOG_BYTES = 10 * 1024 * 1024
    LOG_BACKUP_COUNT = 10
    LOG_DIR = BASE_DIR / 'logs'

    # Cache settings
    CACHE_OPTIONS = {
        'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        # hiredis C extension: 3-5x faster than pure-Python parser
        # pip install hiredis
        #'PARSER_CLASS': 'redis.connection.HiredisParser',
        'SOCKET_CONNECT_TIMEOUT': 5,
        'SOCKET_TIMEOUT': 5,
        'CONNECTION_POOL_KWARGS': {
            'max_connections': 50,
            'retry_on_timeout': True,
        },
        # Compress cache values > 1KB — reduces Redis memory usage
        'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        # Never crash the app if Redis is temporarily down
        'IGNORE_EXCEPTIONS': True,
    }
    CACHE_BACKEND = 'django_redis.cache.RedisCache'

    # Media
    MEDIA_ROOT = BASE_DIR / 'media'

    # Celery beat intervals
    ANALYTICS_UPDATE_INTERVAL = 300.0

    # WebSocket
    WEBSOCKET_ALLOWED_ORIGINS = os.getenv('WEBSOCKET_ALLOWED_ORIGINS', 'wss://primebooks.sale').split(',')

    # Database routing
    DATABASE_ROUTERS = ['django_tenants.routers.TenantSyncRouter']

# =============================================================================
# SYNC CONFIGURATION
# =============================================================================

if IS_DESKTOP:
    # ✅ Desktop mode: Don't set SYNC_SERVER_URL
    # Let SyncManager auto-detect based on schema/subdomain:
    #   - Compiled (production)  → https://{schema}.primebooks.sale
    #   - Not compiled (dev)     → http://{schema}.localhost:8000

    # Don't set SYNC_SERVER_URL - auto-detection will handle it
    SYNC_AUTH_TOKEN = ''  # Set after login

    # Update server (for version updates) - already set above in desktop section

else:
    # ✅ Web mode: Traditional server URLs
    if DEBUG:
        SYNC_SERVER_URL = 'http://localhost:8000'
        UPDATE_SERVER_URL = 'http://localhost:8000'
    else:
        # Production
        SYNC_SERVER_URL = 'https://primebooks.sale'
        UPDATE_SERVER_URL = 'https://primebooks.sale'

    SYNC_AUTH_TOKEN = ''

# =============================================================================
# SHARED CONFIGURATION (Common to all modes)
# =============================================================================

# Create log directory
os.makedirs(LOG_DIR, exist_ok=True)

# Application definition
SHARED_APPS = [
    'django_tenants',
    'primebooks',
    'saad',
    'company',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'rest_framework',
    'django_countries',
    'django_extensions',
    'public_accounts',
    'public_admin',
    'referral',
    'public_router',
    'public_seo',
    'public_blog',
    'public_analytics',
    'public_support',
    'widget_tweaks',
    'django_filters',
    "crispy_forms",
    "crispy_bootstrap5",
    'corsheaders',
    'changelog',
]
LOCAL_DEV_PORT = 8000
# Add web-specific apps only for web mode
if not IS_DESKTOP:
    SHARED_APPS.insert(1, 'daphne')  # ASGI server for channels
    SHARED_APPS.extend(['django_celery_beat', 'django_celery_results', 'channels', 'channels_redis'])

TENANT_APPS = [
    'django.contrib.auth',
    'django.contrib.admin',
    'rest_framework.authtoken',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'accounts.apps.AccountsConfig',
    'branches',
    'stores',
    'inventory',
    'sync',
    'sales',
    'messaging',
    'expenses',
    'reports',
    'invoices',
    'customers',
    'core',
    'notifications',
    'efris',
    'errors',
    'taggit',
    'pos_app',
    'onboarding',
    'suggestions',
    'support_widget',
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]
TAGGIT_CASE_INSENSITIVE = True

# ============================================================================
# MIDDLEWARE CONFIGURATION
# ============================================================================

# ================= BASE MIDDLEWARE (ALWAYS FIRST) =================
MIDDLEWARE = [
    # 🔥 CRITICAL: Tenant detection MUST be FIRST!
    'django_tenants.middleware.main.TenantMainMiddleware',
    'tenancy.middleware.TenantAwareMiddleware',

    # Security & CORS
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',

    # Session & Common
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.locale.LocaleMiddleware',

    # Messages (needs session)
    'django.contrib.messages.middleware.MessageMiddleware',

    # 🔥 AUTH AFTER SCHEMA IS SET
    'referral.middleware.PartnerSessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',

    # Clickjacking protection
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'primebooks.middleware.sequence_reset.SequenceResetMiddleware',
    'primebooks.middleware.sequence_guardian.SequenceGuardianMiddleware',
]

# ================= DESKTOP MODE SPECIFIC =================
if IS_DESKTOP:
    MIDDLEWARE += [
        'primebooks.middleware.desktop_tenant.DesktopTenantMiddleware',
    ]

# ================= WEB MODE SPECIFIC =================
if not IS_DESKTOP:
    if not DEBUG:
        MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

    MIDDLEWARE += [
        'accounts.middleware.StrictSingleSessionMiddleware',
        'accounts.middleware.SaaSAdminAccessMiddleware',
        'accounts.middleware.HiddenUserMiddleware',
        'accounts.middleware.SaaSAdminContextMiddleware',
        'accounts.middleware.AuditMiddleware',
        'public_accounts.middleware.PublicSchemaAuthMiddleware',
        'public_seo.middleware.SEORedirectMiddleware',
        'public_admin.middleware.PublicStaffAuthMiddleware',
        'public_analytics.middleware.AnalyticsMiddleware',
        'errors.middleware.CustomErrorMiddleware',
    ]

# ================= COMMON (BOTH MODES) =================
MIDDLEWARE += [
    # Company-level guards (schema-aware)
    'company.middleware.CompanyAccessMiddleware',
    'company.middleware.PlanLimitsMiddleware',
    'company.middleware.EFRISStatusMiddleware',

    # Messaging (schema-aware)
    'messaging.middleware.EncryptionKeyMiddleware',
    'messaging.middleware.MessageAuditMiddleware',

    # Permissions & Store access (schema-aware)
    'accounts.middleware.RefreshPermissionsMiddleware',
    'stores.middleware.StoreAccessMiddleware',
]

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Default SaaS Admin
DEFAULT_SAAS_ADMIN_EMAIL = os.getenv('DEFAULT_SAAS_ADMIN_EMAIL', 'admin@saas.com')
DEFAULT_SAAS_ADMIN_PASSWORD = os.getenv('DEFAULT_SAAS_ADMIN_PASSWORD', 'saas_admin_2024')

ROOT_URLCONF = 'tenancy.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.navigation_context_processor',
                'company.context_processors.efris_settings',
                'notifications.context_processors.notifications_context',
                'company.context_processors.current_company',
                'branches.context_processors.current_store',
                'stores.context_processors.store_context',
                'support_widget.context_processors.support_widget_context',
                'stores.context_processors.current_store',
                'accounts.context_processors.saas_admin_context',
                'accounts.context_processors.user_role_context',
                'accounts.context_processors.version_context',
                'accounts.context_processors.maintenance_info',
                'errors.context_processors.error_context_processor',
                'messaging.context_processors.messaging_context',
                'public_seo.context_processors.seo_metadata',
                'onboarding.views.onboarding_context',
                'changelog.views.changelog_context',
            ],
        },
    },
]
REPORT_ADMIN_EMAIL = os.getenv('REPORT_ADMIN_EMAIL', 'primefocusug@gmail.com')
SITE_URL = FRONTEND_URL
WSGI_APPLICATION = 'tenancy.wsgi.application'

# ASGI only for web mode (needed for channels/websockets)
if not IS_DESKTOP:
    ASGI_APPLICATION = 'tenancy.asgi.application'

# Channel Layers - Only for web mode
if not IS_DESKTOP and REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [REDIS_URL],
                "capacity": 1500,
                "expiry": 10,
            },
        },
    }

EXPENSE_ATTACHMENT_ALLOWED_TYPES = [
    'image/jpeg', 'image/png', 'image/gif',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]

EXPENSE_ATTACHMENT_MAX_SIZE = 5 * 1024 * 1024

# Caches
if IS_DESKTOP:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': CACHE_BACKEND,
            'LOCATION': f'{REDIS_URL}/1',
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                **CACHE_OPTIONS
            },
            'KEY_PREFIX': 'tenant',
            'VERSION': 1,
        }
    }

SHARING_LOCK_THRESHOLD = 70           # score 0-100 that triggers auto-lock
SHARING_IMPOSSIBLE_TRAVEL_SPEED = 800 # km/h (commercial flight)
SHARING_FINGERPRINT_WINDOW_HOURS = 2  # rolling window for fingerprint check
SHARING_FINGERPRINT_MAX_DISTINCT = 2  # max unique fingerprints before flag
SHARING_CONCURRENT_WINDOW_SECONDS = 30

#Celery Configuration - Only for web mode
if not IS_DESKTOP and REDIS_URL:
    CELERY_BROKER_URL        = f'{REDIS_URL}/0'
    CELERY_RESULT_BACKEND    = f'{REDIS_URL}/2'   # ✅ FIX: separate DB from broker (/0) and cache (/1)
    CELERY_ACCEPT_CONTENT    = ['json']
    CELERY_TASK_SERIALIZER   = 'json'
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_TIMEZONE          = TIME_ZONE           # ✅ FIX: always in sync with Django TIME_ZONE

    # ── Beat schedule ─────────────────────────────────────────────────────────
    # ✅ FIX: removed `if CELERY_AVAILABLE:` guard — Celery is a hard dependency
    # for web mode. The outer `if not IS_DESKTOP and REDIS_URL:` is sufficient.
    # The old guard caused CELERY_BEAT_SCHEDULE to silently become {} when the
    # celery import failed at startup, meaning NO scheduled tasks would ever run.
    CELERY_BEAT_SCHEDULE = {

        # ── Company / subscription lifecycle ─────────────────────────────────
        'check-company-access': {
            'task': 'company.tasks.check_company_access_status',
            'schedule': crontab(minute=0, hour='*/6'),          # Every 6 hours
        },
        'check-trial-expirations': {
            'task': 'company.tasks.check_trial_expirations',
            'schedule': crontab(hour=1, minute=0),              # Daily  01:00
        },
        'check-subscription-expirations': {
            'task': 'company.tasks.check_subscription_expirations',
            'schedule': crontab(hour=1, minute=30),             # Daily  01:30
        },

        # ── Reports — broadcast emails ────────────────────────────────────────
        'daily-report-all-tenants': {
            'task': 'reports.tasks.dispatch_daily_reports',
            'schedule': crontab(hour=8, minute=0),              # Daily  08:00
        },
        'weekly-report-all-tenants': {
            'task': 'reports.tasks.dispatch_weekly_reports',
            'schedule': crontab(hour=8, minute=30, day_of_week=1),  # Monday 08:30
        },

        # ── Reports — user-configured schedules ──────────────────────────────
        'process-scheduled-reports': {
            'task': 'reports.tasks.process_scheduled_reports',
            'schedule': crontab(minute='*/5'),                  # Every 5 minutes
        },

        # ── Reports — housekeeping ────────────────────────────────────────────
        # ✅ ADDED: deletes expired GeneratedReport files + DB records
        'cleanup-expired-reports': {
            'task': 'reports.tasks.cleanup_expired_reports',
            'schedule': crontab(hour=2, minute=30),             # Daily  02:30
        },
        # ✅ ADDED: moves completed reports >90 days old to /archived_reports/
        'archive-old-reports': {
            'task': 'reports.tasks.archive_old_reports',
            'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Sunday 03:00
        },

        # ── Real-time dashboard + stock/EFRIS alerts ──────────────────────────
        # ✅ ADDED: fans out to update_dashboard_cache, check_stock_alerts,
        #           check_efris_compliance for every tenant
        'update-real-time-dashboard': {
            'task': 'reports.tasks.update_real_time_dashboard',
            'schedule': crontab(minute='*/5'),                  # Every 5 minutes
        },

        # ── Sign-up / onboarding cleanup ─────────────────────────────────────
        'cleanup-failed-signups': {
            'task': 'public_router.tasks.cleanup_failed_signups',
            'schedule': crontab(minute='*/5'),                  # Every 5 minutes
        },
        'cleanup-stale-signups': {
            'task': 'public_router.tasks.cleanup_stale_pending_signups',
            'schedule': crontab(minute='*/15'),                 # Every 15 minutes
        },

        # ── Analytics ────────────────────────────────────────────────────────
        'generate-daily-analytics': {
            'task': 'public_analytics.tasks.generate_daily_stats',
            'schedule': crontab(hour=1, minute=0),              # Daily  01:00
        },

        # ── Messaging ────────────────────────────────────────────────────────
        'cleanup-old-statistics': {
            'task': 'messaging.tasks.cleanup_old_statistics',
            'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Sunday 02:00
        },
    }

    CELERY_TASK_ROUTES = {
        'public_router.tasks.create_tenant_async': {'queue': 'tenant_creation'},
        'public_router.tasks.send_welcome_email': {'queue': 'emails'},
    }
    CELERY_WORKER_CONCURRENCY = 4
    CELERY_WORKER_PREFETCH_MULTIPLIER = 1

    CELERY_TASK_ANNOTATIONS = {
        'public_router.tasks.create_tenant_async': {
            'rate_limit': '10/m',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

SITE_ID = 1

# Internationalization
LANGUAGE_CODE = 'en-us'
# TIME_ZONE is defined near the top of this file (after the pytz import) so
# it is available to both the maintenance block and the Celery config block.
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('en', _('English')),
    ('fr', _('French')),
    ('es', _('Spanish')),
    ('lg', _('luganda')),
    ('lm', _('lugisu')),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

# Authentication
AUTH_USER_MODEL = 'accounts.CustomUser'
if IS_DESKTOP:
    AUTHENTICATION_BACKENDS = [
        'public_accounts.backends.PublicIdentifierBackend',
        'company.authentication.CompanyAwareAuthBackend',
        'accounts.backends.RoleBasedAuthBackend',
    ]
else:
    AUTHENTICATION_BACKENDS = [
        'referral.auth_backend.PartnerAuthBackend',
        'public_accounts.backends.PublicIdentifierBackend',
        'company.authentication.CompanyAwareAuthBackend',
        'accounts.backends.RoleBasedAuthBackend',
        'django.contrib.auth.backends.ModelBackend',
    ]

VERSION_MAJOR = 1
VERSION_MINOR = 0
DEPLOYMENT_YEAR = 2025
DEPLOYMENT_MONTH = 12
DEPLOYMENT_DAY = 1
APP_VERSION = f"{VERSION_MAJOR}.{VERSION_MINOR}.{DEPLOYMENT_YEAR}{DEPLOYMENT_MONTH:02d}{DEPLOYMENT_DAY:02d}"

# Django Tenants - Define for both modes (models need it)
TENANT_MODEL = "company.Company"
TENANT_DOMAIN_MODEL = "company.Domain"

# These only apply to web mode
if not IS_DESKTOP:
    TENANT_HEADER = 'X-Company-ID'
    PUBLIC_SCHEMA_NAME = 'public'
    PUBLIC_SCHEMA_URLCONF = 'tenancy.public_urls'
    SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'

# EFRIS Settings
EFRIS_WEBSOCKET_SETTINGS = {
    'CONNECTION_TIMEOUT': 300,
    'HEARTBEAT_INTERVAL': 30,
    'MAX_CONNECTIONS_PER_COMPANY': 50,
    'MESSAGE_SIZE_LIMIT': 1024 * 10,
}

SIGNUP_NOTIFICATION_EMAILS = [
    'primefocusug@gmail.com',
    # add more as needed
]

EFRIS_ENABLED = True
EFRIS_DEFAULT_ENVIRONMENT = os.getenv('EFRIS_ENVIRONMENT', 'sandbox')
EFRIS_DEFAULT_MODE = 'online'
EFRIS_SANDBOX_URL = 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'
EFRIS_PRODUCTION_URL = 'https://efrisws.ura.go.ug/ws/taapp/getInformation'

# Error Handlers
handler403 = 'errors.views.error_403_view'
handler404 = 'errors.views.error_404_view'
handler500 = 'errors.views.error_500_view'

ERROR_PAGE_SETTINGS = {
    'SITE_NAME': SITE_NAME,
    'SUPPORT_EMAIL': SUPPORT_EMAIL,
    'TWITTER_HANDLE': os.getenv('TWITTER_HANDLE', '@primebooks'),
    'ENABLE_ERROR_LOGGING': True,
    'LOG_USER_AGENTS': True,
}

# Invoice Settings
INVOICE_SETTINGS = {
    'DEFAULT_PAYMENT_TERMS_DAYS': 30,
    'ENABLE_EFRIS_INTEGRATION': True,
    'EFRIS_API_URL': EFRIS_SANDBOX_URL,
}

# File Upload Settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
COMPANY_LOGO_MAX_SIZE = 2 * 1024 * 1024
EMPLOYEE_PHOTO_MAX_SIZE = 1 * 1024 * 1024

# Default values
DEFAULT_CURRENCY = 'UGX'
DEFAULT_COUNTRY = 'UG'
TRIAL_PERIOD_DAYS = 60
GRACE_PERIOD_DAYS = 7
MAX_LOGO_SIZE_MB = 2
MAX_EMPLOYEE_PHOTO_SIZE_MB = 1

# settings.py
LICENSE_HMAC_SECRET = "207e8e9bb591d0d93774e98117506acef52bf72abe2e728fc92601571e31b00c"

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': REST_FRAMEWORK_THROTTLE_RATES,
}


SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',

    'JTI_CLAIM': 'jti',

    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DEFAULT_FILE_STORAGE = 'django_tenants.files.storage.TenantFileSystemStorage'

# =============================================================================
# LOGGING
# =============================================================================
# LOG_LEVEL / CONSOLE_LOG_LEVEL are set in each mode block above.
# This dict is intentionally defined once here so it picks up those values.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        },
        'json': {
            # Requires python-json-logger: pip install python-json-logger
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'level': locals().get('CONSOLE_LOG_LEVEL', 'WARNING'),
        },
    },
    'root': {
        'handlers': ['console'],
        'level': locals().get('LOG_LEVEL', 'WARNING'),
    },
    'loggers': {
        # Suppress per-query SQL logs — very noisy and slow at scale
        'django.db.backends': {
            'level': 'ERROR',
            'handlers': ['console'],
            'propagate': False,
        },
        # Keep sales/EFRIS at INFO so fiscalization events remain visible
        'sales': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        'efris': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
    },
}