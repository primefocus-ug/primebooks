from pathlib import Path
from datetime import timedelta
from celery.schedules import crontab
from django.utils.translation import gettext_lazy as _
import os

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-9mghr4buf3l(sinf2(lez20c&*=2)lha_qkdyrxeu1#14@p&(%')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# Hosts
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',') if not DEBUG else ['*']

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
]

# Add WhiteNoise for production static files
if not DEBUG:
    MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')

MIDDLEWARE.extend([
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
])

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

WSGI_APPLICATION = 'tenancy.wsgi.application'
ASGI_APPLICATION = 'tenancy.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django_tenants.postgresql_backend',
        'NAME': os.getenv('DB_NAME', 'mbalei'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', '@Developer25'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# Production database optimization
if not DEBUG:
    DATABASES['default']['CONN_MAX_AGE'] = 600
    DATABASES['default']['OPTIONS'] = {
        'connect_timeout': 10,
        'sslmode': os.getenv('DB_SSLMODE', 'require'),
    }

DATABASE_ROUTERS = ('django_tenants.routers.TenantSyncRouter',)

# Redis/Cache/Celery Configuration
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379')

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

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'{REDIS_URL}/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'tenant',
        'VERSION': 1,
    }
}

# Production cache optimization
if not DEBUG:
    CACHES['default']['OPTIONS'].update({
        'SOCKET_CONNECT_TIMEOUT': 5,
        'SOCKET_TIMEOUT': 5,
        'CONNECTION_POOL_KWARGS': {
            'max_connections': 50,
            'retry_on_timeout': True
        }
    })

# Celery Configuration
CELERY_BROKER_URL = f'{REDIS_URL}/0'
CELERY_RESULT_BACKEND = f'{REDIS_URL}/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Africa/Kampala'
CELERY_TASK_ALWAYS_EAGER = DEBUG  # Run tasks synchronously in development
CELERY_TASK_EAGER_PROPAGATES = DEBUG

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
        'schedule': 300.0 if not DEBUG else 60.0,
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

# Email Configuration
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'company.email.TenantAwareEmailBackend'

EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@yourdomain.com')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'support@yourdomain.com')

# Site Configuration
SITE_NAME = os.getenv('SITE_NAME', 'Prime Books')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:8000' if DEBUG else 'https://primebooks.sale')

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

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

if not DEBUG:
    SESSION_COOKIE_AGE = 1209600  # 2 weeks
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'

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

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# CORS
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', '').split(',')
    CORS_ALLOW_CREDENTIALS = True

# WebSocket
WEBSOCKET_ALLOWED_ORIGINS = os.getenv('WEBSOCKET_ALLOWED_ORIGINS', 'http://localhost:8000').split(',')

# Security Settings (Production only)
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Lax'
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')

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
        'user': '1000/day' if DEBUG else '5000/day',
        'anon': '100/day' if DEBUG else '500/day',
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

# Logging
LOG_DIR = BASE_DIR / 'logs'
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} [{name}] {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'simple' if DEBUG else 'verbose',
        },
        'tenant_file': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'companies.log',
            'maxBytes': 5 * 1024 * 1024 if DEBUG else 10 * 1024 * 1024,
            'backupCount': 3 if DEBUG else 10,
            'formatter': 'verbose',
        },
        'tenant_general_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'tenant.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5 if DEBUG else 10,
            'formatter': 'verbose',
        },
        'invoice_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'invoices.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5 if DEBUG else 10,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django_tenants': {
            'handlers': ['tenant_general_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'company': {
            'handlers': ['tenant_file', 'console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'tenant_middleware': {
            'handlers': ['tenant_general_file', 'console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'invoices': {
            'handlers': ['invoice_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# Add security logging in production
if not DEBUG:
    LOGGING['handlers']['security_file'] = {
        'level': 'WARNING',
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / 'security.log',
        'maxBytes': 10 * 1024 * 1024,
        'backupCount': 10,
        'formatter': 'verbose',
    }
    LOGGING['loggers']['django.security'] = {
        'handlers': ['security_file', 'console'],
        'level': 'WARNING',
        'propagate': False,
    }

# Print mode on startup
if DEBUG:
    print("=" * 50)
    print("🔧 RUNNING IN DEVELOPMENT MODE")
    print("=" * 50)
else:
    print("=" * 50)
    print("🚀 RUNNING IN PRODUCTION MODE")
    print("=" * 50)