# primebooks/routers.py
"""
Database router for desktop multi-tenancy
Works alongside django-tenants router

🔥 CRITICAL FIX: Company model ALWAYS uses default database
"""
from threading import local
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

_thread_locals = local()


def set_current_tenant(tenant_id):
    """Set the current tenant ID for this thread"""
    _thread_locals.tenant_id = tenant_id
    if tenant_id:
        logger.debug(f"Router: Set tenant to {tenant_id}")
    else:
        logger.debug("Router: Cleared tenant (using default)")


def get_current_tenant():
    """Get the current tenant ID for this thread"""
    return getattr(_thread_locals, 'tenant_id', None)


class DesktopTenantRouter:
    """
    Routes database operations to tenant-specific databases in desktop mode
    Only active when IS_DESKTOP=True

    🔥 CRITICAL: Company model ALWAYS uses default database
    """

    # Apps that should always use the default database
    SHARED_APPS = [
        'company',  # 🔥 CRITICAL - Company always in default DB
        'primebooks',
        'contenttypes',
        'sessions',
        'messages',
        'staticfiles',
        'humanize',
        'rest_framework',
        'django_countries',
        'django_extensions',
        'public_accounts',
        'public_admin',
        'public_router',
        'public_seo',
        'public_blog',
        'public_analytics',
        'public_support',
        'widget_tweaks',
        'django_filters',
        'crispy_forms',
        'crispy_bootstrap5',
        'corsheaders',
        'django_tenants',
    ]

    def _is_desktop_mode(self):
        """Check if we're in desktop mode"""
        return getattr(settings, 'IS_DESKTOP', False)

    def _get_tenant_db(self):
        """Get the database name for current tenant"""
        tenant_id = get_current_tenant()
        if tenant_id:
            db_name = f'tenant_{tenant_id}'
            logger.debug(f"Router: Using tenant DB: {db_name}")
            return db_name
        logger.debug("Router: No tenant set, using default")
        return 'default'

    def _is_company_model(self, model):
        """Check if this is the Company model or related to it"""
        # Check if it's the Company model itself
        if model._meta.app_label == 'company' and model._meta.model_name == 'company':
            return True

        # Check if it's Domain model (related to Company)
        if model._meta.app_label == 'company' and model._meta.model_name == 'domain':
            return True

        return False

    def db_for_read(self, model, **hints):
        """Route read operations"""
        # Only route in desktop mode
        if not self._is_desktop_mode():
            return None

        # 🔥 CRITICAL: Company model ALWAYS uses default database
        if self._is_company_model(model):
            logger.debug(f"Router READ: {model._meta.label} → default (Company model)")
            return 'default'

        # Check if this is a shared app
        if model._meta.app_label in self.SHARED_APPS:
            logger.debug(f"Router READ: {model._meta.label} → default (shared app)")
            return 'default'

        # Use tenant database if one is set
        db = self._get_tenant_db()
        logger.debug(f"Router READ: {model._meta.label} → {db}")
        return db

    def db_for_write(self, model, **hints):
        """Route write operations"""
        # Only route in desktop mode
        if not self._is_desktop_mode():
            return None

        # 🔥 CRITICAL: Company model ALWAYS uses default database
        if self._is_company_model(model):
            logger.debug(f"Router WRITE: {model._meta.label} → default (Company model)")
            return 'default'

        # Check if this is a shared app
        if model._meta.app_label in self.SHARED_APPS:
            logger.debug(f"Router WRITE: {model._meta.label} → default (shared app)")
            return 'default'

        # Use tenant database if one is set
        db = self._get_tenant_db()
        logger.debug(f"Router WRITE: {model._meta.label} → {db}")
        return db

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations if both objects are in compatible databases"""
        if not self._is_desktop_mode():
            return None

        # 🔥 ALLOW relations between tenant models and Company
        # This is critical for Store → Company relationships
        if self._is_company_model(obj1._meta.model) or self._is_company_model(obj2._meta.model):
            logger.debug(f"Router RELATION: Allowing {obj1._meta.label} ↔ {obj2._meta.label} (Company involved)")
            return True

        # Get databases for both objects
        db1 = obj1._state.db or 'default'
        db2 = obj2._state.db or 'default'

        # Allow relations within the same database
        if db1 == db2:
            logger.debug(f"Router RELATION: Allowing {obj1._meta.label} ↔ {obj2._meta.label} (same DB: {db1})")
            return True

        # Allow relations between default and tenant databases
        # This handles ForeignKey relationships like Store.company
        if (db1 == 'default' or db2 == 'default') or \
                (db1.startswith('tenant_') or db2.startswith('tenant_')):
            logger.debug(f"Router RELATION: Allowing {obj1._meta.label} ↔ {obj2._meta.label} (cross-DB: {db1} ↔ {db2})")
            return True

        logger.debug(f"Router RELATION: Blocking {obj1._meta.label} ↔ {obj2._meta.label}")
        return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Control which apps can be migrated to which databases"""
        if not self._is_desktop_mode():
            return None

        # Shared apps only migrate to default
        if app_label in self.SHARED_APPS:
            should_migrate = db == 'default'
            logger.debug(f"Router MIGRATE: {app_label} → {db}: {should_migrate} (shared app)")
            return should_migrate

        # Tenant apps can migrate to any tenant database or default
        if db == 'default':
            logger.debug(f"Router MIGRATE: {app_label} → {db}: True")
            return True

        if db.startswith('tenant_'):
            logger.debug(f"Router MIGRATE: {app_label} → {db}: True")
            return True

        logger.debug(f"Router MIGRATE: {app_label} → {db}: False")
        return False
