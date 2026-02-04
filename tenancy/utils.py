# tenancy/utils.py
"""
Utility functions for handling multi-tenancy in both web and desktop modes.
"""
from django.conf import settings
from django.db import connection
import logging

logger = logging.getLogger(__name__)


class tenant_context_safe:
    """
    Context manager that safely handles tenant switching in both modes.
    - Desktop mode: Uses database routing via thread-local storage
    - Web mode: Uses django-tenants schema_context
    """

    def __init__(self, tenant):
        self.tenant = tenant
        self.is_desktop = getattr(settings, 'IS_DESKTOP', False)
        self.previous_tenant = None

    def __enter__(self):
        if self.is_desktop:
            # Desktop mode: Set tenant via router
            from primebooks.routers import set_current_tenant, get_current_tenant
            self.previous_tenant = get_current_tenant()

            # Get the company_id (primary key) from the tenant
            company_id = getattr(self.tenant, 'company_id', None)

            # Set the tenant ID for routing (using company_id as PK)
            set_current_tenant(company_id)

            # Also set on connection for compatibility
            connection.tenant = self.tenant
            connection.schema_name = getattr(self.tenant, 'schema_name', f'desktop_{company_id}')

            return self
        else:
            # Web mode: Use django-tenants
            from django_tenants.utils import schema_context
            self._context = schema_context(self.tenant.schema_name)
            return self._context.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_desktop:
            # Restore previous tenant
            from primebooks.routers import set_current_tenant
            set_current_tenant(self.previous_tenant)
            return False
        else:
            return self._context.__exit__(exc_type, exc_val, exc_tb)


def get_current_schema():
    """
    Get the current schema name in a mode-agnostic way.
    """
    if getattr(settings, 'IS_DESKTOP', False):
        from primebooks.routers import get_current_tenant
        tenant_id = get_current_tenant()
        return f'desktop_{tenant_id}' if tenant_id else 'desktop'
    else:
        return getattr(connection, 'schema_name', 'public')


def get_current_tenant():
    """
    Get the current tenant object in a mode-agnostic way.
    """
    if getattr(settings, 'IS_DESKTOP', False):
        from primebooks.routers import get_current_tenant as get_tenant_id
        company_id = get_tenant_id()  # This is now company_id (string PK)
        if company_id:
            from company.models import Company
            try:
                # Use company_id as primary key
                return Company.objects.using('default').get(company_id=company_id)
            except Company.DoesNotExist:
                return None
        return None
    else:
        return getattr(connection, 'tenant', None)


def is_public_schema():
    """
    Check if we're currently in the public schema.
    """
    if getattr(settings, 'IS_DESKTOP', False):
        from primebooks.routers import get_current_tenant
        return get_current_tenant() is None
    else:
        schema_name = getattr(connection, 'schema_name', 'public')
        public_schema_name = getattr(settings, 'PUBLIC_SCHEMA_NAME', 'public')
        return schema_name == public_schema_name


def switch_tenant(tenant):
    """
    Immediately switch to a different tenant (not a context manager).
    Use with caution - prefer tenant_context_safe for automatic cleanup.
    """
    if getattr(settings, 'IS_DESKTOP', False):
        from primebooks.routers import set_current_tenant
        tenant_id = getattr(tenant, 'id', None)
        set_current_tenant(tenant_id)
        connection.tenant = tenant
        connection.schema_name = getattr(tenant, 'schema_name', f'desktop_{tenant_id}')
    else:
        from django_tenants.utils import schema_context
        # Note: This should be used within a context manager in web mode
        connection.set_tenant(tenant)


class schema_context_safe:
    """
    Safe wrapper for schema_context that works in both desktop and web modes.

    In desktop mode:
    - Uses the router to switch databases
    - Sets connection attributes for compatibility

    In web mode:
    - Uses django-tenants schema_context

    Usage:
        with schema_context_safe(schema_name):
            # Your code here
            pass
    """

    def __init__(self, schema_name):
        self.schema_name = schema_name
        self.is_desktop = getattr(settings, 'IS_DESKTOP', False)
        self.previous_tenant = None
        self._context = None

    def __enter__(self):
        if self.is_desktop:
            # Desktop mode
            from primebooks.routers import set_current_tenant, get_current_tenant

            self.previous_tenant = get_current_tenant()

            # For desktop mode, schema_name is like "desktop_PF-N233072"
            # Extract tenant ID from schema name
            if self.schema_name and self.schema_name.startswith('desktop_'):
                # Extract the company_id (which is the primary key)
                company_id = self.schema_name.replace('desktop_', '')

                try:
                    # Set the tenant using company_id (string primary key)
                    set_current_tenant(company_id)

                    # Get tenant object and set on connection
                    from company.models import Company
                    try:
                        # Query using company_id as the primary key
                        tenant = Company.objects.using('default').get(company_id=company_id)
                        connection.tenant = tenant
                        connection.schema_name = self.schema_name
                    except Company.DoesNotExist:
                        logger.warning(f"Tenant with company_id {company_id} not found")
                        pass
                except Exception as e:
                    logger.error(f"Error setting tenant for schema {self.schema_name}: {e}")
                    pass

            elif self.schema_name == 'public' or self.schema_name == 'desktop':
                # Public schema - no tenant
                set_current_tenant(None)
                connection.schema_name = 'desktop'
            else:
                # Unknown schema name format in desktop mode
                logger.warning(f"Unknown schema name format in desktop mode: {self.schema_name}")

            return self
        else:
            # Web mode - use django-tenants
            try:
                from django_tenants.utils import schema_context
                self._context = schema_context(self.schema_name)
                return self._context.__enter__()
            except Exception as e:
                logger.error(f"Error entering schema context for '{self.schema_name}': {e}")
                return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_desktop:
            # Restore previous tenant
            from primebooks.routers import set_current_tenant
            set_current_tenant(self.previous_tenant)
            return False
        else:
            if self._context:
                return self._context.__exit__(exc_type, exc_val, exc_tb)
            return False