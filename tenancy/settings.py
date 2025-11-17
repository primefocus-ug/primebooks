from pathlib import Path
from datetime import timedelta
from celery.schedules import crontab
from django.utils.translation import gettext_lazy as _
import os

# Load environment variables
from dotenv import load_dotenv

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file - MUST happen before any other imports or logic
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# CRITICAL: Determine DEBUG mode first
DEBUG_VALUE = os.getenv('DEBUG', 'True')  # Default to True if not set
DEBUG = DEBUG_VALUE.strip().lower() in ('true', '1', 'yes', 'on')


# =============================================================================
# DEVELOPMENT vs PRODUCTION CONFIGURATION
# =============================================================================

if DEBUG:
    # =========================================================================
    # DEVELOPMENT MODE - Uses hardcoded values
    # =========================================================================
    print("=" * 50)
    print("🔧 RUNNING IN DEVELOPMENT MODE")
    print("=" * 50)

    SECRET_KEY = 'django-insecure-9mghr4buf3l(sinf2(lez20c&*=2)lha_qkdyrxeu1#14@p&(%'
    ALLOWED_HOSTS = ['*']
    PUBLIC_ADMIN_URL = 'http://localhost:8000'
    # Database
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

    # Email - Console backend for development
    EMAIL_BACKEND = 'company.email.TenantAwareEmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = 'kondenationafrica@gmail.com'
    EMAIL_HOST_PASSWORD = 'ckpbealacabdnyal'
    DEFAULT_FROM_EMAIL = 'noreply@yourdomain.com'
    SUPPORT_EMAIL = 'support@yourdomain.com'

    # Site
    FRONTEND_URL = 'http://localhost:8000'
    SITE_NAME = 'Prime Books'
    # Base domain for tenant subdomains
    BASE_DOMAIN = os.getenv('BASE_DOMAIN', default='localhost')  # e.g., 'yoursaas.com'

    # Use SSL in production
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

    # Static files - No WhiteNoise in development
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

    # Sessions
    SESSION_COOKIE_AGE = 86400  # 1 day
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

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

    # Cache settings
    CACHE_OPTIONS = {}

    # Celery beat schedule intervals
    ANALYTICS_UPDATE_INTERVAL = 60.0

else:
    # =========================================================================
    # PRODUCTION MODE - Loads from .env
    # =========================================================================
    print("=" * 50)
    print("🚀 RUNNING IN PRODUCTION MODE")
    print("=" * 50)

    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set in production")

    # Clean and parse host lists
    ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'primebooks.sale').split(',')]
    PUBLIC_ADMIN_URL = 'https://primebooks.sale'
    # Database
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
            }
        }
    }

    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

    # Email - Tenant-aware backend for production
    EMAIL_BACKEND = 'company.email.TenantAwareEmailBackend'
    EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@primebooks.sale')
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'support.primebooks@gmail.com')

    # Site
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://primebooks.sale')
    SITE_NAME = os.getenv('SITE_NAME', 'Prime Books')
    BASE_DOMAIN = os.getenv('BASE_DOMAIN', 'primebooks.sale')
    USE_SSL = os.getenv('USE_SSL', 'True').lower() in ('true', '1', 'yes')


    # CORS
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [h.strip() for h in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if h.strip()]
    CORS_ALLOW_CREDENTIALS = True

    # Security - Enabled for production
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

    # Static files - WhiteNoise for production
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

    # Sessions
    SESSION_COOKIE_AGE = 1209600  # 2 weeks
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Lax'

    # Celery
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_TASK_EAGER_PROPAGATES = False

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

    # Cache settings
    CACHE_OPTIONS = {
        'SOCKET_CONNECT_TIMEOUT': 5,
        'SOCKET_TIMEOUT': 5,
        'CONNECTION_POOL_KWARGS': {
            'max_connections': 50,
            'retry_on_timeout': True
        }
    }

    # Celery beat schedule intervals
    ANALYTICS_UPDATE_INTERVAL = 300.0

# =============================================================================
# SHARED CONFIGURATION (Common to both modes)
# =============================================================================

# Application definition
SHARED_APPS = [
    'daphne',
    'django_tenants',
    'company',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'rest_framework',
    'django_countries',
    'django_celery_beat',
    'django_celery_results',
    'channels',
    'django_extensions',
    'public_accounts',
    'public_admin',
    'public_router',
    'public_seo',
    'public_blog',
    'public_analytics',
    'public_support',
    'channels_redis',
    'widget_tweaks',
    'django_filters',
    "crispy_forms",
    "crispy_bootstrap5",
]

TENANT_APPS = [
    'django.contrib.auth',
    'django.contrib.admin',
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
    'messaging',
    'expenses',
    'reports',
    'invoices',
    'customers',
    'core',
    'notifications',
    'efris',
    'errors',
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

# Middleware
MIDDLEWARE = [
    'django_tenants.middleware.main.TenantMainMiddleware',
    'django.middleware.security.SecurityMiddleware',
]

# Add WhiteNoise for production only
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
    'company.middleware.PlanLimitsMiddleware',
    'company.middleware.EFRISStatusMiddleware', 
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'tenancy.middleware.TenantAwareMiddleware',
    'accounts.middleware.SaaSAdminAccessMiddleware',
    'accounts.middleware.HiddenUserMiddleware',
    'accounts.middleware.SaaSAdminContextMiddleware',
    'accounts.middleware.AuditMiddleware',
    'public_accounts.middleware.PublicSchemaAuthMiddleware',
    'errors.middleware.CustomErrorMiddleware',
    'messaging.middleware.EncryptionKeyMiddleware',
    'messaging.middleware.MessageAuditMiddleware',
    'accounts.middleware.RefreshPermissionsMiddleware',
    'public_seo.middleware.SEORedirectMiddleware',
    'public_admin.middleware.PublicStaffAuthMiddleware',
    'public_analytics.middleware.AnalyticsMiddleware',
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
                'company.context_processors.efris_settings',
                'notifications.context_processors.notifications_context',
                'company.context_processors.current_company',
                'branches.context_processors.current_store',
                'stores.context_processors.current_store',
                'accounts.context_processors.saas_admin_context',
                'accounts.context_processors.user_role_context',
                'errors.context_processors.error_context_processor',
                'messaging.context_processors.messaging_context',
                'expenses.context_processors.expense_context',
                'public_seo.context_processors.seo_metadata',
            ],
        },
    },
]

WSGI_APPLICATION = 'tenancy.wsgi.application'
ASGI_APPLICATION = 'tenancy.asgi.application'

DATABASE_ROUTERS = ('django_tenants.routers.TenantSyncRouter',)

# Channel Layers
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
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'{REDIS_URL}/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            **CACHE_OPTIONS
        },
        'KEY_PREFIX': 'tenant',
        'VERSION': 1,
    }
}

# Celery Configuration
CELERY_BROKER_URL = f'{REDIS_URL}/0'
CELERY_RESULT_BACKEND = f'{REDIS_URL}/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Africa/Kampala'

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
        'schedule': ANALYTICS_UPDATE_INTERVAL,
    },
    'generate-daily-statistics': {
        'task': 'messaging.tasks.generate_message_analytics',
        'schedule': crontab(hour=0, minute=5),  # Daily at 00:05
    },
    'cleanup-failed-signups': {
        'task': 'public_router.tasks.cleanup_failed_signups',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'cleanup-stale-signups': {
        'task': 'public_router.tasks.cleanup_stale_pending_signups',
        'schedule': crontab(minute='*/15'),  # Every 15 minutes
    },
    'generate-daily-analytics': {
        'task': 'public_analytics.tasks.generate_daily_stats',
        'schedule': crontab(hour=1, minute=0),  # 1 AM daily
    },
    'cleanup-old-statistics': {
        'task': 'messaging.tasks.cleanup_old_statistics',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Weekly on Sunday at 2am
    },

    'send-admin-digest': {
        'task': 'messaging.tasks.send_admin_digest_email',
        'schedule': crontab(hour=8, minute=0),  # Daily at 8am
        'args': (1,),  # Replace with actual admin user ID
    },
}
CELERY_TASK_ROUTES = {
    'public_router.tasks.create_tenant_async': {'queue': 'tenant_creation'},
    'public_router.tasks.send_welcome_email': {'queue': 'emails'},
}
CELERY_WORKER_CONCURRENCY = 4  # Adjust based on your resources
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Prevent worker from grabbing too many tasks

# Rate limiting for tenant creation
CELERY_TASK_ANNOTATIONS = {
    'public_router.tasks.create_tenant_async': {
        'rate_limit': '10/m',  # Max 10 tenant creations per minute
    }
}
# WebSocket
WEBSOCKET_ALLOWED_ORIGINS = os.getenv('WEBSOCKET_ALLOWED_ORIGINS',
                                      'http://localhost:8000' if DEBUG else 'wss://primebooks.sale').split(',')

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

# Authentication
AUTH_USER_MODEL = 'accounts.CustomUser'
AUTHENTICATION_BACKENDS = [
    'public_accounts.backends.PublicIdentifierBackend',
    'company.authentication.CompanyAwareAuthBackend',
    'accounts.backends.RoleBasedAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Django Allauth
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_UNIQUE_EMAIL = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
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
        },
        'REDIRECT_URI': 'http://localhost:8000/accounts/google/login/callback/',
    }
}

# Django Tenants
TENANT_MODEL = "company.Company"
TENANT_DOMAIN_MODEL = "company.Domain"
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
MEDIA_ROOT = BASE_DIR / 'media'

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
    'DEFAULT_THROTTLE_RATES': REST_FRAMEWORK_THROTTLE_RATES,
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
        'json': {
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s'
        } if not DEBUG else {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': CONSOLE_LOG_LEVEL,
            'class': 'logging.StreamHandler',
            'formatter': 'simple' if DEBUG else 'verbose',
        },
        'tenant_file': {
            'level': LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'companies.log',
            'maxBytes': MAX_LOG_BYTES,
            'backupCount': LOG_BACKUP_COUNT,
            'formatter': FILE_LOG_FORMATTER if not DEBUG else 'verbose',
        },
        'tenant_general_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'tenant.log',
            'maxBytes': MAX_LOG_BYTES,
            'backupCount': LOG_BACKUP_COUNT,
            'formatter': FILE_LOG_FORMATTER if not DEBUG else 'verbose',
        },
        'invoice_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'invoices.log',
            'maxBytes': MAX_LOG_BYTES,
            'backupCount': LOG_BACKUP_COUNT,
            'formatter': FILE_LOG_FORMATTER if not DEBUG else 'verbose',
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
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'tenant_middleware': {
            'handlers': ['tenant_general_file', 'console'],
            'level': LOG_LEVEL,
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
        'maxBytes': MAX_LOG_BYTES,
        'backupCount': LOG_BACKUP_COUNT,
        'formatter': 'json',
    }
    LOGGING['loggers']['django.security'] = {
        'handlers': ['security_file', 'console'],
        'level': 'WARNING',
        'propagate': False,
    }