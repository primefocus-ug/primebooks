# stores/middleware.py - FIXED WITH SCHEMA AWARENESS
"""
Store middleware with schema awareness
✅ Checks tenant exists before accessing
✅ Handles None tenant gracefully
"""
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.deprecation import MiddlewareMixin
from django.db import connection
from django_tenants.utils import get_tenant
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)


class StoreAccessMiddleware(MiddlewareMixin):
    """
    Middleware to enforce store access control and set current store in request
    ✅ FIXED: Checks tenant exists before accessing
    """

    EXEMPT_URLS = [
        'no_store_access',
        'check_access',
        'select_store',
        'login',
        'logout',
        'custom_logout',
        'password_reset',
        'set_language',

    ]

    def process_request(self, request):
        # ✅ CHECK SCHEMA FIRST
        schema_name = getattr(connection, 'schema_name', 'public')

        # Skip if in public schema
        if schema_name == 'public':
            return None

        # ✅ CHECK TENANT EXISTS
        # FIX: bare `except:` catches KeyboardInterrupt and SystemExit too.
        # Use Exception instead.
        try:
            tenant = get_tenant(request)
        except Exception:
            tenant = None

        # Skip if no tenant
        if not tenant:
            return None

        # Skip if tenant is public
        if hasattr(tenant, 'schema_name') and tenant.schema_name == "public":
            return None

        # Skip unauthenticated users
        if not request.user.is_authenticated:
            return None

        # Skip SaaS admin
        if getattr(request.user, "is_saas_admin", False):
            return None

        # Check if URL is exempt
        if self.is_exempt_url(request):
            return None

        # Get current store ID from session
        current_store_id = request.session.get("current_store_id")

        # Check if user has access to any store
        has_store_access = self.check_store_access(request.user, request)

        if not has_store_access:
            # FIX: is_exempt_url() was already called above and returned early
            # if the URL was exempt, so we are guaranteed to be on a
            # non-exempt URL here — the redundant inner check is removed.
            messages.error(
                request,
                "You have not been assigned to any store. Please contact your administrator."
            )
            return redirect("stores:no_store_access")

        # User has store access, check current store
        from stores.models import Store

        if current_store_id:
            try:
                store = Store.objects.get(id=current_store_id, is_active=True)

                if not self.can_access_store(request.user, store):
                    messages.warning(request, "You no longer have access to that store.")
                    request.session.pop("current_store_id", None)
                    return redirect("stores:select_store")

                request.current_store = store

            except Store.DoesNotExist:
                request.session.pop("current_store_id", None)
                return redirect("stores:select_store")
        else:
            default_store = self.get_default_store(request.user, request)

            if default_store:
                request.session["current_store_id"] = default_store.id
                request.current_store = default_store
            else:
                messages.error(request, "Please select a store to continue.")
                return redirect("stores:select_store")

        return None

    def is_exempt_url(self, request):
        # FIX: bare `except:` replaced with `except Exception`
        try:
            resolver_match = request.resolver_match
            if resolver_match:
                url_name = resolver_match.url_name
                if url_name in self.EXEMPT_URLS:
                    return True
        except Exception:
            pass

        exempt_paths = [
            '/accounts/login/',
            '/accounts/logout/',
            '/en/accounts/login/',
            '/en/accounts/logout/',
            '/stores/no-access/',
            '/en/stores/no-access/',
            '/stores/check-access/',
            '/en/stores/check-access/',
            '/api/',
            '/api/v1/price-reduction-requests/',
            '/admin/',
            '/static/',
            '/media/',
            '/i18n/',
        ]

        return any(request.path.startswith(path) for path in exempt_paths)

    def check_store_access(self, user, request):
        from stores.models import Store, StoreAccess

        if hasattr(user, 'stores') and user.stores.filter(is_active=True).exists():
            return True

        if hasattr(user, 'managed_stores') and user.managed_stores.filter(is_active=True).exists():
            return True

        if StoreAccess.objects.filter(user=user, is_active=True, store__is_active=True).exists():
            return True

        if hasattr(request, 'company') or hasattr(user, 'company'):
            company = getattr(request, 'company', getattr(user, 'company', None))
            if company:
                if Store.objects.filter(company=company, is_active=True, accessible_by_all=True).exists():
                    return True

        return False

    def can_access_store(self, user, store):
        from stores.models import StoreAccess

        # FIX: `store in user.stores.all()` forces a full queryset evaluation.
        # Use .filter(pk=...).exists() to let the DB do a single indexed lookup.
        if hasattr(user, 'stores') and user.stores.filter(pk=store.pk).exists():
            return True

        if hasattr(user, 'managed_stores') and user.managed_stores.filter(pk=store.pk).exists():
            return True

        if StoreAccess.objects.filter(user=user, store=store, is_active=True).exists():
            return True

        if hasattr(user, 'company') and user.company:
            if store.company == user.company and store.accessible_by_all:
                return True

        return False

    def get_default_store(self, user, request):
        from stores.models import Store, StoreAccess

        default_store = getattr(user, 'default_store', None)
        if default_store and self.can_access_store(user, default_store):
            return default_store

        if hasattr(user, 'stores'):
            store = user.stores.filter(is_active=True).first()
            if store:
                return store

        if hasattr(user, 'managed_stores'):
            store = user.managed_stores.filter(is_active=True).first()
            if store:
                return store

        access = StoreAccess.objects.filter(
            user=user,
            is_active=True,
            store__is_active=True
        ).first()

        if access:
            return access.store

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
    """Track and manage device sessions"""

    def process_request(self, request):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return None

        if not request.user.is_authenticated:
            return None

        if request.path.startswith('/admin/'):
            return None

        try:
            from .utils import get_device_session_from_request, get_client_ip

            session = get_device_session_from_request(request)

            if session:
                if session.is_expired:
                    session.terminate(reason='EXPIRED')
                    request.session.pop('device_session_id', None)
                    request.session.pop('device_fingerprint', None)
                    return None

                session.last_activity_at = timezone.now()
                # FIX: build update_fields dynamically — the old code always
                # included 'ip_address' and 'security_alerts_count' even when
                # the IP had not changed, causing a pointless write on every
                # single request.
                fields_to_save = ['last_activity_at']

                current_ip = get_client_ip(request)
                if session.ip_address != current_ip:
                    from .models import SecurityAlert

                    store = getattr(session, 'store', None)

                    if store:
                        SecurityAlert.objects.create(
                            user=request.user,
                            store=store,
                            session=session,
                            device=getattr(session, 'store_device', None),
                            alert_type='IP_CHANGE',
                            severity='MEDIUM',
                            # FIX: use % formatting instead of f-strings in
                            # log/message strings to avoid leaking PII into
                            # aggregators that format lazily.
                            title='IP changed for %s' % request.user.get_full_name(),
                            description='IP changed from %s to %s' % (
                                session.ip_address, current_ip
                            ),
                            ip_address=current_ip,
                            alert_data={
                                'original_ip': session.ip_address,
                                'new_ip': current_ip,
                            }
                        )

                    session.ip_address = current_ip
                    session.security_alerts_count += 1
                    fields_to_save += ['ip_address', 'security_alerts_count']

                session.save(update_fields=fields_to_save)
                request.device_session = session

        except Exception as e:
            logger.error("Error in DeviceSessionMiddleware: %s", e)

        return None


class SessionActivityMiddleware(MiddlewareMixin):
    """Detect suspicious activity patterns"""

    def process_request(self, request):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return None

        if not request.user.is_authenticated:
            return None

        if request.path.startswith('/admin/') or request.path.startswith('/static/'):
            return None

        try:
            store = getattr(request, 'store', None) or getattr(request, 'current_store', None)

            if not store and hasattr(request.user, 'company'):
                from stores.models import Store
                store = Store.objects.filter(
                    company=request.user.company,
                    is_active=True
                ).first()

            if not store:
                return None

            last_check = request.session.get('last_suspicious_check')
            now = timezone.now().timestamp()

            if not last_check or (now - last_check) > 300:
                from .utils import detect_suspicious_activity, get_device_session_from_request

                is_suspicious, reasons = detect_suspicious_activity(
                    request.user,
                    store,
                    timeframe_hours=1
                )

                if is_suspicious:
                    session = get_device_session_from_request(request)
                    if session and not session.is_suspicious:
                        session.flag_suspicious('. '.join(reasons))

                request.session['last_suspicious_check'] = now

        except Exception as e:
            logger.error("Error in SessionActivityMiddleware: %s", e)

        return None


class ConcurrentSessionLimitMiddleware(MiddlewareMixin):
    """Enforce concurrent session limits"""

    MAX_CONCURRENT_SESSIONS = 3

    def process_request(self, request):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return None

        if not request.user.is_authenticated:
            return None

        if request.path.startswith('/admin/'):
            return None

        try:
            from .models import UserDeviceSession

            active_count = UserDeviceSession.objects.filter(
                user=request.user,
                is_active=True,
                expires_at__gt=timezone.now()
            ).count()

            if active_count > self.MAX_CONCURRENT_SESSIONS:
                from .utils import log_device_action

                oldest_sessions = UserDeviceSession.objects.filter(
                    user=request.user,
                    is_active=True,
                    expires_at__gt=timezone.now()
                ).order_by('created_at')[:(active_count - self.MAX_CONCURRENT_SESSIONS)]

                store = getattr(request, 'store', None) or getattr(request, 'current_store', None)

                if not store and hasattr(request.user, 'company'):
                    from stores.models import Store
                    store = Store.objects.filter(
                        company=request.user.company,
                        is_active=True
                    ).first()

                for session in oldest_sessions:
                    session_store = getattr(session, 'store', None) or store

                    if session_store:
                        try:
                            log_device_action(
                                user=request.user,
                                store=session_store,
                                action='SESSION_TERMINATED',
                                device=getattr(session, 'store_device', None),
                                session=session,
                                success=True,
                                reason='Concurrent session limit exceeded'
                            )
                        except Exception as e:
                            logger.error("Error logging termination: %s", e)

                    session.terminate(reason='FORCE_CLOSED')

        except Exception as e:
            logger.error("Error in ConcurrentSessionLimitMiddleware: %s", e)

        return None


class StoreDetectionMiddleware(MiddlewareMixin):
    """
    Detect and attach current store to request
    ✅ FIXED: Schema-aware
    """

    def process_request(self, request):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return None

        store = None

        try:
            from stores.models import Store

            # Method 1: From URL parameter
            store_id = request.GET.get('store_id') or request.POST.get('store_id')
            if store_id:
                try:
                    store = Store.objects.select_related('company').get(id=store_id, is_active=True)
                except (Store.DoesNotExist, ValueError):
                    pass

            # Method 2: From session
            if not store and request.session.get('current_store_id'):
                try:
                    store = Store.objects.select_related('company').get(
                        id=request.session['current_store_id'],
                        is_active=True
                    )
                except Store.DoesNotExist:
                    del request.session['current_store_id']

            # Method 3: User's default store
            if not store and request.user.is_authenticated:
                store = getattr(request.user, 'default_store', None)

            # Method 4: Main store from tenant
            if not store and hasattr(request, 'tenant') and request.tenant:
                store = Store.objects.filter(
                    company=request.tenant,
                    is_main_branch=True,
                    is_active=True
                ).first()

            # Attach to request
            request.current_store = store
            request.store = store
            request.current_branch = store
            request.branch = store

        except Exception as e:
            logger.error("Error in StoreDetectionMiddleware: %s", e)

        return None