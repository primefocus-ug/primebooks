from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.deprecation import MiddlewareMixin
from .utils import (
    get_device_session_from_request,
    detect_suspicious_activity,
    get_client_ip
)
from django_tenants.utils import get_tenant
from django.urls import reverse


class StoreAccessMiddleware(MiddlewareMixin):
    """
    Middleware to enforce store access control and set current store in request
    """

    # Define URLs that should be exempt from store access checks
    EXEMPT_URLS = [
        'no_store_access',  # Store no access page
        'check_access',  # Store access check API
        'select_store',  # Store selection page
        'login',  # Login page
        'logout',  # Logout page
        'custom_logout',  # Custom logout
        'password_reset',  # Password reset
        'set_language',  # Language switcher
    ]

    def is_exempt_url(self, request):
        """Check if the current URL should be exempt from store access checks"""
        # Get the URL name from the request
        try:
            resolver_match = request.resolver_match
            if resolver_match:
                url_name = resolver_match.url_name
                return url_name in self.EXEMPT_URLS
        except:
            pass

        # Check by path patterns
        exempt_paths = [
            '/accounts/login/',
            '/accounts/logout/',
            '/en/accounts/login/',
            '/en/accounts/logout/',
            '/stores/no-access/',  # Your no_store_access URL path
            '/en/stores/no-access/',
            '/stores/check-access/',
            '/en/stores/check-access/',
            '/api/',  # API endpoints
            '/admin/',  # Admin site
            '/static/',  # Static files
            '/media/',  # Media files
            '/i18n/',  # Django i18n
        ]

        for path in exempt_paths:
            if request.path.startswith(path):
                return True

        return False

    def process_request(self, request):
        tenant = get_tenant(request)

        # 🔒 Skip public schema entirely
        if tenant.schema_name == "public":
            return None

        # Skip unauthenticated users
        if not request.user.is_authenticated:
            return None

        # Skip SaaS admin safely
        if getattr(request.user, "is_saas_admin", False):
            return None

        # Check if URL is exempt
        if self.is_exempt_url(request):
            return None

        # Get current store ID from session
        current_store_id = request.session.get("current_store_id")

        # Check if user has access to any store
        has_store_access = self.check_store_access(request.user, request)

        # If user doesn't have ANY store access, redirect to no_store_access
        if not has_store_access:
            # Don't redirect if we're already on the no_access page
            if not self.is_exempt_url(request):
                messages.error(
                    request,
                    "You have not been assigned to any store. Please contact your administrator."
                )
                return redirect("stores:no_store_access")
            return None

        # User has store access, now check if they have a current store selected
        from stores.models import Store

        if current_store_id:
            try:
                store = Store.objects.get(id=current_store_id, is_active=True)

                # Check if user can access this specific store
                if not self.can_access_store(request.user, store):
                    messages.warning(request, "You no longer have access to that store.")
                    request.session.pop("current_store_id", None)
                    # Redirect to store selection page
                    return redirect("stores:select_store")

                request.current_store = store

            except Store.DoesNotExist:
                request.session.pop("current_store_id", None)
                # Redirect to store selection page
                return redirect("stores:select_store")
        else:
            # User has store access but no store selected
            # Try to get a default or first accessible store
            default_store = self.get_default_store(request.user, request)

            if default_store:
                request.session["current_store_id"] = default_store.id
                request.current_store = default_store
            else:
                # This shouldn't happen if has_store_access is True, but just in case
                messages.error(
                    request,
                    "Please select a store to continue."
                )
                return redirect("stores:select_store")

        return None

    def check_store_access(self, user, request):
        """
        Check if user has access to any active store
        """
        from stores.models import Store, StoreAccess

        # Check through multiple access methods
        if hasattr(user, 'stores') and user.stores.filter(is_active=True).exists():
            return True

        if hasattr(user, 'managed_stores') and user.managed_stores.filter(is_active=True).exists():
            return True

        # Check store access permissions
        if StoreAccess.objects.filter(
                user=user,
                is_active=True,
                store__is_active=True
        ).exists():
            return True

        # Check company-wide access
        if hasattr(request, 'company') or hasattr(user, 'company'):
            company = getattr(request, 'company', getattr(user, 'company', None))
            if company:
                if Store.objects.filter(
                        company=company,
                        is_active=True,
                        accessible_by_all=True
                ).exists():
                    return True

        return False

    def can_access_store(self, user, store):
        """
        Check if user can access a specific store
        """
        from stores.models import StoreAccess

        # Direct store assignment
        if hasattr(user, 'stores') and store in user.stores.all():
            return True

        # Store manager assignment
        if hasattr(user, 'managed_stores') and store in user.managed_stores.all():
            return True

        # Store access permissions
        if StoreAccess.objects.filter(
                user=user,
                store=store,
                is_active=True
        ).exists():
            return True

        # Company-wide access
        if hasattr(user, 'company') and user.company:
            if store.company == user.company and store.accessible_by_all:
                return True

        return False

    def get_default_store(self, user, request):
        """
        Get a default store for the user
        """
        from stores.models import Store

        # Try user's default store property
        default_store = getattr(user, 'default_store', None)
        if default_store and self.can_access_store(user, default_store):
            return default_store

        # Try to find any accessible store
        if hasattr(user, 'stores'):
            store = user.stores.filter(is_active=True).first()
            if store:
                return store

        if hasattr(user, 'managed_stores'):
            store = user.managed_stores.filter(is_active=True).first()
            if store:
                return store

        # Check store access permissions
        from stores.models import StoreAccess
        access = StoreAccess.objects.filter(
            user=user,
            is_active=True,
            store__is_active=True
        ).first()

        if access:
            return access.store

        # Company-wide accessible stores
        if hasattr(request, 'company') or hasattr(user, 'company'):
            company = getattr(request, 'company', getattr(user, 'company', None))
            if company:
                store = Store.objects.filter(
                    company=company,
                    is_active=True,
                    accessible_by_all=True
                ).first()
                if store:
                    return store

        return None

class DeviceSessionMiddleware(MiddlewareMixin):
    """
    Middleware to track and manage device sessions
    """

    def process_request(self, request):
        """
        Check and update device session on each request
        """
        if not request.user.is_authenticated:
            return None

        # Skip for admin requests
        if request.path.startswith('/admin/'):
            return None

        # Get current device session
        session = get_device_session_from_request(request)

        if session:
            # Check if session is expired
            if session.is_expired:
                session.terminate(reason='EXPIRED')
                # Clear session data
                request.session.pop('device_session_id', None)
                request.session.pop('device_fingerprint', None)
                return None

            # Update last activity
            session.last_activity_at = timezone.now()

            # Check for IP change (potential session hijacking)
            current_ip = get_client_ip(request)
            if session.ip_address != current_ip:
                from .models import SecurityAlert

                # ✅ FIX: Safely get store from session
                store = getattr(session, 'store', None)

                if store:  # Only create alert if store exists
                    SecurityAlert.objects.create(
                        user=request.user,
                        store=store,
                        session=session,
                        device=getattr(session, 'store_device', None),
                        alert_type='IP_CHANGE',
                        severity='MEDIUM',
                        title=f'IP address changed during session for {request.user.get_full_name()}',
                        description=f'Session IP changed from {session.ip_address} to {current_ip}',
                        ip_address=current_ip,
                        alert_data={
                            'original_ip': session.ip_address,
                            'new_ip': current_ip,
                            'session_age': str(timezone.now() - session.created_at),
                        }
                    )

                # Update session IP
                session.ip_address = current_ip
                session.security_alerts_count += 1

            session.save(update_fields=['last_activity_at', 'ip_address', 'security_alerts_count'])

            # Attach session to request for easy access
            request.device_session = session

        return None


class SessionActivityMiddleware(MiddlewareMixin):
    """
    Middleware to detect suspicious activity patterns
    """

    def process_request(self, request):
        """
        Check for suspicious activity on each request
        """
        if not request.user.is_authenticated:
            return None

        # Skip for admin and static requests
        if request.path.startswith('/admin/') or request.path.startswith('/static/'):
            return None

        # ✅ FIX: Safely get store from multiple sources
        store = getattr(request, 'store', None)

        if not store:
            store = getattr(request, 'current_store', None)

        if not store and hasattr(request.user, 'company'):
            try:
                from stores.models import Store
                store = Store.objects.filter(
                    company=request.user.company,
                    is_active=True
                ).first()
            except Exception:
                pass

        if not store:
            return None

        # Run suspicious activity detection periodically (not on every request)
        # Check if we should run detection (stored in session)
        last_check = request.session.get('last_suspicious_check')
        now = timezone.now().timestamp()

        # Run check every 5 minutes
        if not last_check or (now - last_check) > 300:
            try:
                is_suspicious, reasons = detect_suspicious_activity(
                    request.user,
                    store,
                    timeframe_hours=1
                )

                if is_suspicious:
                    # Mark current session as suspicious if it exists
                    session = get_device_session_from_request(request)
                    if session and not session.is_suspicious:
                        session.flag_suspicious('. '.join(reasons))

                # Update last check time
                request.session['last_suspicious_check'] = now
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error detecting suspicious activity: {e}")

        return None


class ConcurrentSessionLimitMiddleware(MiddlewareMixin):
    """
    Middleware to enforce concurrent session limits
    """

    MAX_CONCURRENT_SESSIONS = 3

    def process_request(self, request):
        """
        Check concurrent session limit
        """
        if not request.user.is_authenticated:
            return None

        # Skip for admin requests
        if request.path.startswith('/admin/'):
            return None

        try:
            # Get active sessions count
            from .models import UserDeviceSession

            active_count = UserDeviceSession.objects.filter(
                user=request.user,
                is_active=True,
                expires_at__gt=timezone.now()
            ).count()

            # If over limit, terminate oldest sessions
            if active_count > self.MAX_CONCURRENT_SESSIONS:
                from .utils import log_device_action

                # Get oldest sessions to terminate
                oldest_sessions = UserDeviceSession.objects.filter(
                    user=request.user,
                    is_active=True,
                    expires_at__gt=timezone.now()
                ).order_by('created_at')[:(active_count - self.MAX_CONCURRENT_SESSIONS)]

                # ✅ FIX: Safely get store from multiple sources
                store = getattr(request, 'store', None)

                if not store:
                    store = getattr(request, 'current_store', None)

                if not store and hasattr(request.user, 'company'):
                    try:
                        from stores.models import Store
                        store = Store.objects.filter(
                            company=request.user.company,
                            is_active=True
                        ).first()
                    except Exception:
                        pass

                for session in oldest_sessions:
                    # ✅ FIX: Use store from session if request store not available
                    session_store = getattr(session, 'store', None) or store

                    # Log the termination only if we have a store
                    if session_store:
                        try:
                            log_device_action(
                                user=request.user,
                                store=session_store,
                                action='SESSION_TERMINATED',
                                device=getattr(session, 'store_device', None),
                                session=session,
                                success=True,
                                reason='Concurrent session limit exceeded',
                                terminated_sessions=active_count
                            )
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.error(f"Error logging session termination: {e}")

                    # Terminate session regardless
                    session.terminate(reason='FORCE_CLOSED')

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in ConcurrentSessionLimitMiddleware: {e}")

        return None