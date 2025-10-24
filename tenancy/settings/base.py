from pathlib import Path
from datetime import timedelta
from celery.schedules import crontab
from django.utils.translation import gettext_lazy as _
import os

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Application definition
SHARED_APPS = [
    'django_tenants',
    'company',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'rest_framework',
    'django_countries',
    'channels',
    'channels_redis',
    'widget_tweaks',
    'django_filters',
    "crispy_forms",
    "crispy_bootstrap5",
]

TENANT_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'accounts',
    'branches',
    'stores',
    'inventory',
    'sales',
    'reports',
    'invoices',
    'expenses',
    'customers',
    'core',
    'services',
    'notifications',
    'efris',
    'errors',
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

MIDDLEWARE = [
    'django_tenants.middleware.main.TenantMainMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # For static files in production
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'company.middleware.CompanyAccessMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'tenancy.middleware.TenantAwareMiddleware',
    'accounts.middleware.SaaSAdminAccessMiddleware',
    'accounts.middleware.HiddenUserMiddleware',
    'accounts.middleware.SaaSAdminContextMiddleware',
    'errors.middleware.CustomErrorMiddleware',
]

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Default SaaS Admin
DEFAULT_SAAS_ADMIN_EMAIL = os.getenv('DEFAULT_SAAS_ADMIN_EMAIL', 'admin@saas.com')
DEFAULT_SAAS_ADMIN_PASSWORD = os.getenv('DEFAULT_SAAS_ADMIN_PASSWORD', 'change-me-in-production')

# URL Configuration
ROOT_URLCONF = 'tenancy.urls'

# Templates
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
                'notifications.context_processors.notifications_context',
                'company.context_processors.current_company',
                'branches.context_processors.current_branch',
                'stores.context_processors.current_store',
                'accounts.context_processors.saas_admin_context',
                'errors.context_processors.error_context_processor'
            ],
        },
    },
]

# WSGI/ASGI
WSGI_APPLICATION = 'tenancy.wsgi.application'
ASGI_APPLICATION = 'tenancy.asgi.application'

# Database Router
DATABASE_ROUTERS = ('django_tenants.routers.TenantSyncRouter',)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Kampala'
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

SITE_ID = 1

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Authentication
AUTH_USER_MODEL = 'accounts.CustomUser'
AUTHENTICATION_BACKENDS = [
    'company.authentication.CompanyAwareAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Django Allauth
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_UNIQUE_EMAIL = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'optional'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.CustomSocialAccountAdapter'

# Google OAuth
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'APP': {
            'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID', ''),
            'secret': os.getenv('GOOGLE_OAUTH_CLIENT_SECRET', ''),
            'key': ''
        }
    }
}

# Django Tenants
TENANT_MODEL = "company.Company"
TENANT_DOMAIN_MODEL = "company.Domain"
TENANT_HEADER = 'X-Company-ID'
BASE_DOMAIN = os.getenv('BASE_DOMAIN', 'localhost')
PUBLIC_SCHEMA_NAME = 'public'

# Celery Beat Schedule
CELERY_BEAT_SCHEDULE = {
    'check-company-access': {
        'task': 'company.tasks.check_company_access_status',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    'check-trial-expirations': {
        'task': 'company.tasks.check_trial_expirations',
        'schedule': crontab(hour=1, minute=0),
    },
    'check-subscription-expirations': {
        'task': 'company.tasks.check_subscription_expirations',
        'schedule': crontab(hour=1, minute=30),
    },
    'generate-daily-performance-report': {
        'task': 'company.tasks.generate_daily_reports',
        'schedule': crontab(hour=6, minute=0),
    },
    'analytics-update': {
        'task': 'company.tasks.send_periodic_analytics_update',
        'schedule': 300.0,  # Every 5 minutes
    },
    'efris-daily-maintenance': {
        'task': 'efris.tasks.daily_efris_maintenance',
        'schedule': crontab(hour=2, minute=0),
    },
    'efris-process-sync-queue': {
        'task': 'efris.tasks.process_efris_sync_queue',
        'schedule': 300.0,
    },
}

# EFRIS Settings
EFRIS_WEBSOCKET_SETTINGS = {
    'CONNECTION_TIMEOUT': 300,
    'HEARTBEAT_INTERVAL': 30,
    'MAX_CONNECTIONS_PER_COMPANY': 50,
    'MESSAGE_SIZE_LIMIT': 1024 * 10,
}

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
    'SITE_NAME': os.getenv('SITE_NAME', 'primebooks'),
    'SUPPORT_EMAIL': os.getenv('SUPPORT_EMAIL', 'primebooks@gmail.com'),
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
    'DEFAULT_THROTTLE_RATES': {
        'user': '1000/day',
        'anon': '100/day',
    },
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DEFAULT_FILE_STORAGE = 'django_tenants.files.storage.TenantFileSystemStorage'