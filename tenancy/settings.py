from pathlib import Path
from datetime import timedelta
from celery import shared_task
from django.utils.translation import gettext_lazy as _
from celery.schedules import crontab
import os



# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-9mghr4buf3l(sinf2(lez20c&*=2)lha_qkdyrxeu1#14@p&(%'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


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
TENANT_APPS=[
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
INSTALLED_APPS=list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS ]
MIDDLEWARE = [
    'django_tenants.middleware.main.TenantMainMiddleware',
    'django.middleware.security.SecurityMiddleware',
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
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
DEFAULT_SAAS_ADMIN_EMAIL = 'admin@saas.com'
DEFAULT_SAAS_ADMIN_PASSWORD = 'saas_admin_2024'

ROOT_URLCONF = 'tenancy.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'templates'
        ],
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



DATABASES = {
    'default': {
        'ENGINE': 'django_tenants.postgresql_backend',
        'NAME': 'mbalei',
        'USER': 'postgres',
        'PASSWORD': '@Developer25',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
DATABASE_ROUTERS = (
    'django_tenants.routers.TenantSyncRouter',
)

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('127.0.0.1', 6379)],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://primebooks.sale:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'tenant',
        'VERSION': 1,
    }
}
ERROR_PAGE_SETTINGS = {
    'SITE_NAME': 'Primebooks',
    'SUPPORT_EMAIL': 'primefocusug@gmail.com',
    'TWITTER_HANDLE': '@primebooks',
    'ENABLE_ERROR_LOGGING': True,
    'LOG_USER_AGENTS': True,
}
# CHANNEL_LAYERS={
#     "default": {
#         "BACKEND": "channels.layers.InMemoryChannelLayer"
#     }
# }

# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
#         'LOCATION': 'redis://127.0.0.1:6379/1',
#     }
# }


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

SITE_ID = 1
# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

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
LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

CORS_ALLOW_ALL_ORIGINS = True

AUTH_USER_MODEL='accounts.CustomUser'
AUTHENTICATION_BACKENDS = [
    'company.authentication.CompanyAwareAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

#all auth social logins
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'optional'  # or 'mandatory'
ACCOUNT_UNIQUE_EMAIL = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'optional'

# LOGIN_REDIRECT_URL = '/'  # Change to your dashboard URL
# LOGOUT_REDIRECT_URL = '/accounts/login/'
# ACCOUNT_LOGOUT_REDIRECT_URL = '/accounts/login/'

# Social Account Adapter (for custom user creation)
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.CustomSocialAccountAdapter'

# Google OAuth Settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
        'APP': {
            'client_id': os.environ.get('GOOGLE_OAUTH_CLIENT_ID', ''),
            'secret': os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', ''),
            'key': ''
        }
    }
}

TENANT_MODEL = "company.Company"
TENANT_DOMAIN_MODEL = "company.Domain"
TENANT_HEADER = 'X-Company-ID'
BASE_DOMAIN = 'localhost'
PUBLIC_SCHEMA_NAME = 'public'

CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Africa/Kampala'

CELERY_BEAT_SCHEDULE = {
    'check-company-access': {
        'task': 'company.tasks.check_company_access_status',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    # 'backup-websocket-metrics': {
    #     'task': 'company.tasks.backup_websocket_metrics',
    #     'schedule': 3600.0,  # Every hour
    # },

    # Company lifecycle tasks
    'check-trial-expirations': {
        'task': 'company.tasks.check_trial_expirations',
        'schedule': 86400.0,  # Daily
    },
    'check-subscription-expirations': {
        'task': 'company.tasks.check_subscription_expirations',
        'schedule': 86400.0,  # Daily
    },

    # Reporting tasks
    'generate-daily-performance-report': {
        'task': 'company.tasks.generate_daily_reports',
        'schedule': crontab(hour=6, minute=0),  # Daily at 6 AM
    },

    # System maintenance
    # 'system-health-check': {
    #     'task': 'company.tasks.system_health_check',
    #     'schedule': 1800.0,  # Every 30 minutes
    # },
    'analytics-update': {
        'task': 'company.tasks.send_periodic_analytics_update',
        'schedule': 30.0,  # Every 30 seconds
    },
}

EFRIS_WEBSOCKET_SETTINGS = {
    'CONNECTION_TIMEOUT': 300,  # 5 minutes
    'HEARTBEAT_INTERVAL': 30,   # 30 seconds
    'MAX_CONNECTIONS_PER_COMPANY': 50,
    'MESSAGE_SIZE_LIMIT': 1024 * 10,  # 10KB
}

handler403 = 'errors.views.error_403_view'
handler404 = 'errors.views.error_404_view'
handler500 = 'errors.views.error_500_view'

INVOICE_SETTINGS = {
    'DEFAULT_PAYMENT_TERMS_DAYS': 30,
    'ENABLE_EFRIS_INTEGRATION': True,
    'EFRIS_API_URL': 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation',
    'COMPANY_INFO': {
        'name': 'Prime Focus Ug',
        'address': 'Kampala Ug',
        'phone': '+256 755 777 826',
        'email': 'info@primefocusug.tech',
        'website': 'www.primefocusug.tech',
        'tin': 'Your TIN Number',
    }
}
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS=[
    BASE_DIR / 'static'
]

MEDIA_URL='/media/'
MEDIA_ROOT=BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

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
    'efris-daily-maintenance': {
        'task': 'efris.tasks.daily_efris_maintenance',
        'schedule': crontab(hour=2, minute=0),
    },
    'efris-process-sync-queue': {
        'task': 'efris.tasks.process_efris_sync_queue',
        'schedule': 300.0,
    },
}


DEFAULT_FILE_STORAGE = 'django_tenants.files.storage.TenantFileSystemStorage'

import os

LOG_DIR = BASE_DIR / 'logs'
os.makedirs(LOG_DIR, exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    # Formatters
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

    # Handlers
    'handlers': {
        # Tenant-specific logs
        'tenant_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'companies.log',
            'maxBytes': 5 * 1024 * 1024,  # 5 MB
            'backupCount': 3,
            'formatter': 'verbose',
        },
        # General tenant framework logs
        'tenant_general_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'tenant.log',
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        # Invoice logs
        'invoice_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'invoices.log',
            'formatter': 'verbose',
        },
        # Console logs (dev)
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },

    # Loggers
    'loggers': {
        'django_tenants': {
            'handlers': ['tenant_general_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'company': {
            'handlers': ['tenant_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'tenant_middleware': {
            'handlers': ['tenant_general_file', 'console'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'invoices': {
            'handlers': ['invoice_file'],
            'level': 'INFO',
            'propagate': True,
        },
    },

    # Root logger
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}



EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL')

SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL')
FRONTEND_URL = os.getenv('FRONTEND_URL')
SITE_NAME = os.getenv('SITE_NAME')


if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# Custom settings for your application
COMPANY_LOGO_MAX_SIZE = 2 * 1024 * 1024  # 2MB
EMPLOYEE_PHOTO_MAX_SIZE = 1 * 1024 * 1024  # 1MB
DEFAULT_CURRENCY = 'UGX'
DEFAULT_COUNTRY = 'UG'

WEBSOCKET_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'https://localhost:8000',
    # Add your production domains
]
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
}


# Company-specific settings
TRIAL_PERIOD_DAYS = 60
GRACE_PERIOD_DAYS = 7
MAX_LOGO_SIZE_MB = 2
MAX_EMPLOYEE_PHOTO_SIZE_MB = 1

EFRIS_ENABLED = True
EFRIS_DEFAULT_ENVIRONMENT = 'sandbox'  # or 'production'
EFRIS_DEFAULT_MODE = 'online'  # or 'offline'

# EFRIS URLs
EFRIS_SANDBOX_URL = 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'
EFRIS_PRODUCTION_URL = 'https://efrisws.ura.go.ug/ws/taapp/getInformation'

