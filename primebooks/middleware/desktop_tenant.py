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

    def __init__(self, get_response):
        self.get_response = get_response
        self._cached_tenant = None
        self._cached_tenant_id = None

    def __call__(self, request):
        if not getattr(settings, 'IS_DESKTOP', False):
            return self.get_response(request)

        request._dont_enforce_csrf_checks = True

        if request.path in ['/desktop/sync-status/', '/desktop/syncing/']:
            return self.get_response(request)

        # ── ALWAYS load tenant from credentials (source of truth) ────────────
        # Do NOT rely on session or instance cache as primary source.
        # Session is wiped on user switch; instance cache can be stale.
        # Credentials file is always current after save_credentials().
        tenant_id = self._get_tenant_from_credentials()

        if tenant_id:
            # Update instance cache so Company DB lookup can be cached
            self._cached_tenant_id = tenant_id
            request.session['tenant_id'] = tenant_id
        else:
            # Fallback: try session (covers edge cases during startup)
            tenant_id = request.session.get('tenant_id') or self._cached_tenant_id

        if tenant_id:
            try:
                # Use cached Company object only if it matches current tenant
                if self._cached_tenant and self._cached_tenant.company_id == tenant_id:
                    company = self._cached_tenant
                else:
                    from company.models import Company
                    try:
                        company = Company.objects.get(company_id=tenant_id)
                        self._cached_tenant = company
                    except Company.DoesNotExist:
                        logger.error(f"❌ Company not found: {tenant_id}")
                        self._cached_tenant_id = None
                        self._cached_tenant = None
                        messages.error(request, "Company not found. Please log in again.")
                        return redirect('primebooks:login')

                connection.set_tenant(company)

                request.tenant = company
                request.tenant_id = tenant_id
                request.schema_name = company.schema_name

                if not request.user.is_authenticated:
                    self.auto_login_user(request, company.schema_name)

                if request.user.is_authenticated:
                    logger.debug(f"✓ User: {request.user.email} in schema: {company.schema_name}")

            except Exception as e:
                logger.error(f"❌ Failed to set tenant {tenant_id}: {e}", exc_info=True)
                self._cached_tenant_id = None
                self._cached_tenant = None
                messages.error(request, "An error occurred. Please log in again.")
                return redirect('primebooks:login')
        else:
            logger.warning("⚠️  No tenant found - using public schema")
            connection.set_schema('public')
            request.tenant = None
            request.tenant_id = None
            request.schema_name = 'public'

        return self.get_response(request)

    def _get_tenant_from_credentials(self):
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
        from accounts.models import CustomUser
        from primebooks.auth import DesktopAuthManager

        try:
            auth_manager = DesktopAuthManager()
            user_info = auth_manager.get_user_info()

            if not user_info:
                logger.warning("⚠️  No user info found for auto-login")
                return

            email = user_info.get('email')
            if not email:
                logger.warning("⚠️  No email in user info")
                return

            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                # ── User not in local DB yet — sync them now ─────────────────
                # This happens when switching to a user who has never logged
                # in on this desktop before.
                logger.warning(
                    f"⚠️  User {email} not found in schema {schema_name} — "
                    f"attempting on-demand sync"
                )
                user = self._sync_user_on_demand(auth_manager, email, schema_name)
                if user is None:
                    logger.error(
                        f"❌ Could not sync user {email} — auto-login aborted"
                    )
                    return

            if not user.is_active:
                logger.warning(f"⚠️  User {email} is not active")
                return

            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            logger.info(f"✅ Auto-logged in: {email} (Desktop Mode)")

            if 'pending_login_email' in request.session:
                del request.session['pending_login_email']

        except Exception as e:
            logger.error(f"❌ Auto-login failed: {e}", exc_info=True)

    def _sync_user_on_demand(self, auth_manager, email, schema_name):
        """
        Sync a user from the server into the local tenant DB on demand.
        Called when switching to a user who doesn't exist locally yet.
        Returns the CustomUser instance or None on failure.
        """
        from accounts.models import CustomUser

        try:
            token = auth_manager.get_auth_token()
            company_info = auth_manager.get_company_info()

            if not token or not company_info:
                logger.error("Cannot sync user — missing token or company info")
                return None

            company_id = company_info.get('company_id')
            subdomain = auth_manager.get_subdomain() or schema_name

            logger.info(f"🔄 On-demand sync for user {email} in schema {schema_name}")

            success = auth_manager.sync_user_to_tenant(
                email=email,
                subdomain=subdomain,
                token=token,
                company_id=company_id,
            )

            if not success:
                logger.error(f"sync_user_to_tenant returned False for {email}")
                return None

            # Now try fetching from DB again
            try:
                user = CustomUser.objects.get(email=email)
                logger.info(f"✅ On-demand sync successful: {email} (pk={user.pk})")
                return user
            except CustomUser.DoesNotExist:
                logger.error(f"User {email} still not found after sync")
                return None

        except Exception as e:
            logger.error(f"On-demand user sync failed for {email}: {e}", exc_info=True)
            return None