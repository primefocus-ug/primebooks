# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('/home/prime-focus/current/off/primebooks/templates', 'templates'), ('/home/prime-focus/current/off/primebooks/static', 'static'), ('/home/prime-focus/current/off/primebooks/locale', 'locale'), ('/home/prime-focus/current/off/primebooks/primebooks', 'primebooks'), ('/home/prime-focus/current/off/primebooks/reports/templates', 'reports/templates'), ('/home/prime-focus/current/off/primebooks/sales/templates', 'sales/templates'), ('/home/prime-focus/current/off/primebooks/efris/templates', 'efris/templates'), ('/home/prime-focus/current/off/primebooks/core/templates', 'core/templates'), ('/home/prime-focus/current/off/primebooks/public_accounts/templates', 'public_accounts/templates'), ('/home/prime-focus/current/off/primebooks/expenses/templates', 'expenses/templates'), ('/home/prime-focus/current/off/primebooks/accounts/templates', 'accounts/templates'), ('/home/prime-focus/current/off/primebooks/public_router/templates', 'public_router/templates'), ('/home/prime-focus/current/off/primebooks/public_support/templates', 'public_support/templates'), ('/home/prime-focus/current/off/primebooks/public_seo/templates', 'public_seo/templates'), ('/home/prime-focus/current/off/primebooks/stores/templates', 'stores/templates'), ('/home/prime-focus/current/off/primebooks/customers/templates', 'customers/templates'), ('/home/prime-focus/current/off/primebooks/notifications/templates', 'notifications/templates'), ('/home/prime-focus/current/off/primebooks/pos_app/templates', 'pos_app/templates'), ('/home/prime-focus/current/off/primebooks/messaging/templates', 'messaging/templates'), ('/home/prime-focus/current/off/primebooks/public_admin/templates', 'public_admin/templates'), ('/home/prime-focus/current/off/primebooks/finance/templates', 'finance/templates'), ('/home/prime-focus/current/off/primebooks/public_blog/templates', 'public_blog/templates'), ('/home/prime-focus/current/off/primebooks/invoices/templates', 'invoices/templates'), ('/home/prime-focus/current/off/primebooks/company/templates', 'company/templates'), ('/home/prime-focus/current/off/primebooks/inventory/templates', 'inventory/templates'), ('/home/prime-focus/current/off/primebooks/errors/templates', 'errors/templates'), ('/home/prime-focus/current/off/primebooks/primebooks/templates', 'primebooks/templates'), ('/home/prime-focus/current/off/primebooks/public_analytics/templates', 'public_analytics/templates')]
binaries = []
hiddenimports = ['tenancy', 'tenancy.settings', 'tenancy.urls', 'tenancy.wsgi', 'tenancy.middleware', 'tenancy.celery', 'primebooks', 'primebooks.crash_reporter', 'primebooks.sync_api_views', 'primebooks.updater', 'primebooks.sync', 'primebooks.update_api_views', 'primebooks.urls', 'primebooks.authentication', 'primebooks.auth', 'primebooks.api_urls', 'primebooks.middleware', 'primebooks.postgres_manager', 'primebooks.models', 'primebooks.security', 'primebooks.views', 'primebooks.sync_scheduler', 'primebooks.api_views', 'primebooks.admin', 'primebooks.tests', 'primebooks.sync_dialogs', 'primebooks.apps', 'primebooks.version_manager', 'reports', 'reports.models', 'reports.views', 'reports.urls', 'reports.admin', 'reports.tasks', 'reports.forms', 'reports.serializers', 'sales', 'sales.models', 'sales.views', 'sales.urls', 'sales.admin', 'sales.signals', 'sales.tasks', 'sales.forms', 'sales.serializers', 'sales.context_processors', 'efris', 'efris.models', 'efris.views', 'efris.urls', 'efris.admin', 'efris.signals', 'efris.tasks', 'efris.serializers', 'efris.middleware', 'core', 'core.models', 'core.views', 'core.admin', 'core.middleware', 'core.context_processors', 'public_accounts', 'public_accounts.models', 'public_accounts.views', 'public_accounts.urls', 'public_accounts.admin', 'public_accounts.forms', 'public_accounts.middleware', 'public_accounts.backends', 'expenses', 'expenses.models', 'expenses.views', 'expenses.urls', 'expenses.admin', 'expenses.signals', 'expenses.tasks', 'expenses.forms', 'expenses.serializers', 'expenses.middleware', 'expenses.context_processors', 'accounts', 'accounts.models', 'accounts.views', 'accounts.urls', 'accounts.admin', 'accounts.signals', 'accounts.forms', 'accounts.serializers', 'accounts.middleware', 'accounts.backends', 'accounts.context_processors', 'public_router', 'public_router.models', 'public_router.views', 'public_router.urls', 'public_router.admin', 'public_router.signals', 'public_router.tasks', 'public_router.forms', 'public_support', 'public_support.models', 'public_support.views', 'public_support.urls', 'public_support.admin', 'public_support.forms', 'public_seo', 'public_seo.models', 'public_seo.views', 'public_seo.urls', 'public_seo.admin', 'public_seo.middleware', 'public_seo.context_processors', 'stores', 'stores.models', 'stores.views', 'stores.urls', 'stores.admin', 'stores.signals', 'stores.forms', 'stores.serializers', 'stores.middleware', 'stores.context_processors', 'customers', 'customers.models', 'customers.views', 'customers.urls', 'customers.admin', 'customers.signals', 'customers.tasks', 'customers.forms', 'customers.serializers', 'notifications', 'notifications.models', 'notifications.views', 'notifications.urls', 'notifications.admin', 'notifications.signals', 'notifications.tasks', 'notifications.middleware', 'notifications.context_processors', 'pos_app', 'pos_app.models', 'pos_app.views', 'pos_app.urls', 'pos_app.admin', 'messaging', 'messaging.models', 'messaging.views', 'messaging.urls', 'messaging.admin', 'messaging.signals', 'messaging.tasks', 'messaging.serializers', 'messaging.middleware', 'messaging.context_processors', 'public_admin', 'public_admin.models', 'public_admin.views', 'public_admin.urls', 'public_admin.admin', 'public_admin.middleware', 'finance', 'finance.models', 'finance.views', 'finance.urls', 'finance.admin', 'finance.signals', 'finance.tasks', 'finance.forms', 'finance.serializers', 'branches', 'branches.models', 'branches.views', 'branches.admin', 'branches.signals', 'branches.tasks', 'branches.forms', 'branches.middleware', 'branches.context_processors', 'tenancy', 'tenancy.urls', 'tenancy.middleware', 'public_blog', 'public_blog.models', 'public_blog.views', 'public_blog.urls', 'public_blog.admin', 'public_blog.forms', 'invoices', 'invoices.models', 'invoices.views', 'invoices.urls', 'invoices.admin', 'invoices.tasks', 'invoices.forms', 'invoices.serializers', 'company', 'company.models', 'company.urls', 'company.admin', 'company.signals', 'company.tasks', 'company.forms', 'company.serializers', 'company.middleware', 'company.context_processors', 'inventory', 'inventory.models', 'inventory.views', 'inventory.urls', 'inventory.admin', 'inventory.signals', 'inventory.tasks', 'inventory.forms', 'inventory.serializers', 'errors', 'errors.models', 'errors.views', 'errors.urls', 'errors.admin', 'errors.middleware', 'errors.context_processors', 'primebooks', 'primebooks.models', 'primebooks.views', 'primebooks.urls', 'primebooks.admin', 'primebooks.middleware', 'public_analytics', 'public_analytics.models', 'public_analytics.views', 'public_analytics.urls', 'public_analytics.admin', 'public_analytics.tasks', 'public_analytics.middleware', 'amqp', 'annotated_types', 'asgiref', 'attrs', 'autobahn', 'automat', 'billiard', 'brotli', 'celery', 'certifi', 'cffi', 'channels', 'channels_redis', 'charset_normalizer', 'click', 'click_didyoumean', 'click_plugins', 'click_repl', 'constantly', 'contourpy', 'crispy_bootstrap5', 'cron_descriptor', 'cryptography', 'cssselect2', 'cycler', 'daphne', 'diff_match_patch', 'django', 'django_admin_autocomplete_filter', 'django_allauth', 'django_celery_beat', 'django_celery_results', 'django_cors_headers', 'django_countries', 'django_crispy_forms', 'django_extensions', 'django_filter', 'django_import_export', 'django_js_asset', 'django_mptt', 'django_otp', 'django_rangefilter', 'django_ratelimit', 'django_redis', 'django_taggit', 'django_tenant_users', 'django_tenants', 'django_timezone_field', 'django_widget_tweaks', 'djangorestframework', 'djangorestframework_simplejwt', 'et_xmlfile', 'fonttools', 'gunicorn', 'hyperlink', 'idna', 'incremental', 'kiwisolver', 'kombu', 'matplotlib', 'msgpack', 'numpy', 'openpyxl', 'packaging', 'pandas', 'pillow', 'prompt_toolkit', 'psycopg2_binary', 'pyasn1', 'pyasn1_modules', 'pycparser', 'pycryptodome', 'pycryptodomex', 'pydantic', 'pydantic_core', 'pydyf', 'pyjwt', 'pyopenssl', 'pyotp', 'pyparsing', 'pyphen', 'python_crontab', 'python_dateutil', 'python_dotenv', 'python_json_logger', 'pytz', 'pyzipper', 'qrcode', 'redis', 'reportlab', 'requests', 'sentry_sdk', 'service_identity', 'setuptools', 'six', 'sqlparse', 'structlog', 'tablib', 'timedelta', 'tinycss2', 'tinyhtml5', 'twisted', 'txaio', 'typing_inspection', 'typing_extensions', 'tzdata', 'ua_parser', 'ua_parser_builtins', 'urllib3', 'user_agents', 'vine', 'wcwidth', 'weasyprint', 'webencodings', 'whitenoise', 'xlsxwriter', 'xlwings', 'zope.interface', 'zopfli', 'django', 'django.core', 'django.db', 'django.db.backends.postgresql', 'django.contrib.auth', 'django.contrib.sessions', 'django.contrib.admin', 'django_tenants', 'django_tenants.utils', 'django_tenants.postgresql_backend', 'django_tenants.management', 'django_tenants.management.commands', 'django_tenants.management.commands.migrate_schemas', 'django_tenants.management.commands.create_tenant', 'django_tenants.management.commands.create_superuser_schemas', 'psycopg2', 'psycopg2._psycopg', 'cryptography', 'cryptography.fernet', 'celery', 'celery.app', 'celery.app.base', 'celery.worker', 'celery.exceptions', 'celery.local', 'celery.utils', 'celery.utils.log', 'kombu', 'kombu.transport', 'billiard', 'amqp', 'vine', 'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui', 'PyQt6.QtWebEngineWidgets']
hiddenimports += collect_submodules('primebooks')
hiddenimports += collect_submodules('tenancy')
tmp_ret = collect_all('celery')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('kombu')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('billiard')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('django')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('django_tenants')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('psycopg2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['/home/prime-focus/current/off/primebooks/main.py'],
    pathex=['/home/prime-focus/current/off/primebooks', '/home/prime-focus/current/off/primebooks/tenancy', '/home/prime-focus/current/off/primebooks/primebooks', '/home/prime-focus/current/off/venv/lib/python3.12/site-packages'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PrimeBooks',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
