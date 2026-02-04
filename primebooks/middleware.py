# primebooks/middleware.py
"""
Desktop mode middleware with PostgreSQL multi-tenancy
✅ Sets tenant schema from saved credentials (no session needed)
✅ Auto-login authenticated user
✅ Handles schema initialization gracefully
"""

import logging
from django.conf import settings
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import login
from django_tenants.utils import schema_context
from django.db import connection

logger = logging.getLogger(__name__)


class DesktopTenantMiddleware:
    """
    Routes requests to tenant-specific PostgreSQL schemas in desktop mode
    and automatically logs in the authenticated user.

    ✅ FIXED: Loads tenant from saved credentials (not session)
    ✅ Works automatically after authentication
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._cached_tenant = None
        self._cached_tenant_id = None

    def __call__(self, request):
        # Only run in desktop mode
        if not getattr(settings, 'IS_DESKTOP', False):
            return self.get_response(request)

        request._dont_enforce_csrf_checks = True

        # Skip tenant logic for sync status checks
        if request.path in ['/desktop/sync-status/', '/desktop/syncing/']:
            return self.get_response(request)

        # ✅ TRY 1: Get tenant from session (if set by login)
        tenant_id = request.session.get('tenant_id')

        # ✅ TRY 2: Get tenant from saved credentials (desktop mode)
        if not tenant_id and not self._cached_tenant_id:
            tenant_id = self._get_tenant_from_credentials()
            if tenant_id:
                # Save to cache
                self._cached_tenant_id = tenant_id
                # Also save to session for this request
                request.session['tenant_id'] = tenant_id
                logger.info(f"✅ Loaded tenant from credentials: {tenant_id}")

        if tenant_id:
            try:
                # Get company from database (use cache if available)
                if self._cached_tenant and self._cached_tenant.company_id == tenant_id:
                    company = self._cached_tenant
                else:
                    from company.models import Company
                    try:
                        company = Company.objects.get(company_id=tenant_id)
                        self._cached_tenant = company
                    except Company.DoesNotExist:
                        logger.error(f"❌ Company not found: {tenant_id}")
                        request.session.pop('tenant_id', None)
                        self._cached_tenant_id = None
                        self._cached_tenant = None

                        # In desktop mode, this is critical - redirect to login
                        messages.error(request, "Company not found. Please log in again.")
                        return redirect('primebooks:login')

                # 🔥 CRITICAL: Set tenant for connection BEFORE processing request
                connection.set_tenant(company)

                # Also set on request for convenience
                request.tenant = company
                request.tenant_id = tenant_id
                request.schema_name = company.schema_name

                logger.debug(f"✅ Using tenant: {company.schema_name} ({company.name})")

                # Auto-login if not authenticated
                if not request.user.is_authenticated:
                    self.auto_login_user(request, company.schema_name)

                if request.user.is_authenticated:
                    logger.debug(f"✓ User: {request.user.email} in schema: {company.schema_name}")

            except Exception as e:
                logger.error(f"❌ Failed to set tenant {tenant_id}: {e}", exc_info=True)
                request.session.pop('tenant_id', None)
                self._cached_tenant_id = None
                self._cached_tenant = None
                messages.error(request, "An error occurred. Please log in again.")
                return redirect('primebooks:login')

        else:
            # No tenant selected - use public schema
            logger.warning("⚠️  No tenant found - using public schema")
            connection.set_schema('public')
            request.tenant = None
            request.tenant_id = None
            request.schema_name = 'public'

        response = self.get_response(request)
        return response

    def _get_tenant_from_credentials(self):
        """
        Get tenant ID from saved credentials
        ✅ Desktop mode: credentials are saved locally
        """
        try:
            from primebooks.auth import DesktopAuthManager

            auth_manager = DesktopAuthManager()
            token, user_data, company_data = auth_manager.load_credentials()

            if company_data:
                company_id = company_data.get('company_id')
                schema_name = company_data.get('schema_name')

                logger.info(f"Found credentials: company_id={company_id}, schema={schema_name}")
                return company_id

            logger.debug("No saved credentials found")
            return None

        except Exception as e:
            logger.error(f"Error loading credentials: {e}")
            return None

    def auto_login_user(self, request, schema_name):
        """
        Automatically log in the authenticated user from stored credentials
        ✅ User is already in correct schema context from connection.set_tenant()
        """
        from accounts.models import CustomUser
        from primebooks.auth import DesktopAuthManager

        try:
            # Get stored user info
            auth_manager = DesktopAuthManager()
            user_info = auth_manager.get_user_info()

            if not user_info:
                logger.warning("⚠️  No user info found for auto-login")
                return

            email = user_info.get('email')
            if not email:
                logger.warning("⚠️  No email in user info")
                return

            # ✅ No need for schema_context - already set by connection.set_tenant()
            # Just query directly in current schema
            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                logger.error(f"❌ User {email} not found in schema {schema_name}")
                logger.error(f"   This usually means the user wasn't synced properly during login")
                return

            if not user.is_active:
                logger.warning(f"⚠️  User {email} exists but is not active")
                return

            # Log user in WITHOUT password check (desktop mode - already authenticated)
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            logger.info(f"✅ Auto-logged in: {email} (Desktop Mode)")

            # Clear pending login flag if exists
            if 'pending_login_email' in request.session:
                del request.session['pending_login_email']

        except Exception as e:
            logger.error(f"❌ Auto-login failed: {e}", exc_info=True)