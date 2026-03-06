import hashlib
import uuid
from user_agents import parse
from django.utils import timezone
from datetime import timedelta
import logging
from django.db.models import Q, Count, Sum, F, Max

from .models import Store, StoreDevice, UserDeviceSession, DeviceFingerprint, SecurityAlert, DeviceOperatorLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store access helpers
# ---------------------------------------------------------------------------

def get_user_accessible_stores(user, include_inactive=False):
    """
    Get stores accessible by the user based on permissions and company.
    """
    # SaaS admins can access everything
    if user.is_saas_admin or user.can_access_all_companies:
        queryset = Store.objects.all()

    # Company owners/admins can access all stores in their company
    elif user.is_company_owner or user.company_admin:
        queryset = Store.objects.filter(company=user.company)

    # Regular users: combine multiple access paths via Q objects
    else:
        conditions = Q()

        if hasattr(user, 'stores'):
            staff_store_ids = user.stores.values_list('id', flat=True)
            if staff_store_ids:
                conditions |= Q(id__in=staff_store_ids)

        if hasattr(user, 'managed_stores'):
            managed_store_ids = user.managed_stores.values_list('id', flat=True)
            if managed_store_ids:
                conditions |= Q(id__in=managed_store_ids)

        from .models import StoreAccess
        access_store_ids = StoreAccess.objects.filter(
            user=user,
            is_active=True
        ).values_list('store_id', flat=True)
        if access_store_ids:
            conditions |= Q(id__in=access_store_ids)

        if user.company:
            conditions |= Q(
                company=user.company,
                accessible_by_all=True,
                is_active=True
            )

        if conditions:
            queryset = Store.objects.filter(conditions)
        else:
            queryset = Store.objects.none()

    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    return queryset.select_related('company').distinct()


def get_visible_users_for_store(store, requesting_user):
    """
    Get users visible to the requesting user for a specific store.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    queryset = store.staff.filter(is_active=True, is_hidden=False)

    if requesting_user.is_saas_admin:
        return queryset

    if requesting_user.is_company_owner or requesting_user.company_admin:
        if store.company == requesting_user.company:
            return queryset.select_related('company').distinct()
        return User.objects.none()

    if store.store_managers.filter(id=requesting_user.id).exists():
        return queryset.select_related('company').distinct()

    if store.staff.filter(id=requesting_user.id).exists():
        return queryset.filter(id=requesting_user.id)

    return User.objects.none()


def filter_stores_by_permissions(user, queryset=None, action='view'):
    """
    Filter stores based on user permissions for specific actions.
    """
    if queryset is None:
        return get_user_accessible_stores(user)

    if user.is_saas_admin:
        return queryset

    accessible_stores = get_user_accessible_stores(user)
    return queryset.filter(id__in=accessible_stores.values_list('id', flat=True))


def get_stores_with_statistics(user, store_ids=None):
    """
    Get stores with statistics for dashboard display.
    """
    queryset = get_user_accessible_stores(user)

    if store_ids:
        queryset = queryset.filter(id__in=store_ids)

    return queryset.annotate(
        inventory_count=Count('inventory_items', distinct=True),
        low_stock_count=Count(
            'inventory_items',
            filter=Q(inventory_items__quantity__lte=F('inventory_items__low_stock_threshold')),
            distinct=True
        ),
        total_inventory_value=Sum(
            F('inventory_items__quantity') * F('inventory_items__product__cost_price')
        ),
        device_count=Count('devices', filter=Q(devices__is_active=True), distinct=True),
        staff_count=Count('staff', filter=Q(staff__is_active=True, staff__is_hidden=False), distinct=True),
        manager_count=Count('store_managers', filter=Q(store_managers__is_active=True), distinct=True),
        sales_count=Count('sales', distinct=True),
        total_revenue=Sum('sales__total_amount')
    )


def validate_store_access(user, store, action='view', raise_exception=True):
    """
    Validate if user has access to a specific store.
    """
    from django.core.exceptions import PermissionDenied

    if hasattr(user, 'can_access_store'):
        has_access = user.can_access_store(store)
        if not has_access and raise_exception:
            raise PermissionDenied("You don't have access to this store")
        return has_access

    if user.is_saas_admin or getattr(user, 'can_access_all_companies', False):
        return True

    if not store.company or store.company_id != user.company_id:
        if raise_exception:
            raise PermissionDenied("You don't have access to this store's company")
        return False

    perm = f'stores.{action}_store'
    if not user.has_perm(perm):
        if raise_exception:
            raise PermissionDenied(f"You don't have permission to {action} stores")
        return False

    if not getattr(store, 'accessible_by_all', False):
        is_staff = store.staff.filter(id=user.id).exists()
        is_manager = store.store_managers.filter(id=user.id).exists() if hasattr(store, 'store_managers') else False

        if not (is_staff or is_manager):
            if raise_exception:
                raise PermissionDenied("You don't have access to this specific store")
            return False

    if action in ['delete', 'change']:
        is_manager = store.store_managers.filter(id=user.id).exists() if hasattr(store, 'store_managers') else False
        if not (getattr(user, 'is_company_owner', False) or getattr(user, 'company_admin', False) or is_manager):
            if raise_exception:
                raise PermissionDenied("Insufficient privileges for this action")
            return False

    return True


def filter_session_queryset(user, base_queryset=None):
    """
    Filter device sessions based on user permissions.
    """
    if base_queryset is None:
        base_queryset = UserDeviceSession.objects.all()

    accessible_stores = get_user_accessible_stores(user)

    queryset = base_queryset.filter(
        store__in=accessible_stores,
        user__is_hidden=False
    )

    if not user.is_saas_admin and not getattr(user, 'is_company_owner', False) and not getattr(user, 'company_admin',
                                                                                               False):
        if hasattr(user, 'managed_stores') and user.managed_stores.exists():
            managed_stores = user.managed_stores.all()
            queryset = queryset.filter(store__in=managed_stores)
        else:
            queryset = queryset.filter(user=user)

    return queryset.select_related('user', 'store', 'store_device')


def filter_security_alerts(user, base_queryset=None):
    """
    Filter security alerts based on user permissions.
    """
    if base_queryset is None:
        base_queryset = SecurityAlert.objects.all()

    accessible_stores = get_user_accessible_stores(user)

    queryset = base_queryset.filter(
        store__in=accessible_stores,
        user__is_hidden=False
    )

    if not user.is_saas_admin:
        if getattr(user, 'is_company_owner', False) or getattr(user, 'company_admin', False):
            pass  # See all alerts in company
        elif hasattr(user, 'managed_stores') and user.managed_stores.exists():
            managed_stores = user.managed_stores.all()
            queryset = queryset.filter(store__in=managed_stores)
        else:
            queryset = queryset.filter(user=user)

    return queryset.select_related('user', 'store', 'session', 'device')


# ---------------------------------------------------------------------------
# IP / Location helpers
# ---------------------------------------------------------------------------

def get_client_ip(request):
    """Get the client's real IP address."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_location_from_request(request):
    """
    Extract location data from request (if available from frontend).
    Returns: (latitude, longitude, accuracy, timezone)
    """
    latitude = request.POST.get('latitude') or request.GET.get('latitude')
    longitude = request.POST.get('longitude') or request.GET.get('longitude')
    accuracy = request.POST.get('location_accuracy') or request.GET.get('location_accuracy')
    timezone_str = request.POST.get('timezone') or request.GET.get('timezone', '')

    try:
        latitude = float(latitude) if latitude else None
        longitude = float(longitude) if longitude else None
        accuracy = float(accuracy) if accuracy else None
    except (ValueError, TypeError):
        latitude = longitude = accuracy = None

    return latitude, longitude, accuracy, timezone_str or 'UTC'


# ---------------------------------------------------------------------------
# Device fingerprint
# ---------------------------------------------------------------------------

def generate_device_fingerprint(request):
    """
    Generate a unique device fingerprint from request data.
    Returns: (fingerprint_hash, fingerprint_data)
    """
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = get_client_ip(request)

    try:
        ua = parse(user_agent)
    except Exception as e:
        logger.error(f"Error parsing user agent: {e}")
        return hashlib.sha256(f"{user_agent}|{ip_address}".encode()).hexdigest(), {
            'browser_name': 'Unknown',
            'browser_version': '',
            'os_name': 'Unknown',
            'os_version': '',
            'device_family': 'Unknown',
            'is_mobile': False,
            'is_tablet': False,
            'is_pc': True,
            'is_bot': False,
        }

    fingerprint_components = [
        user_agent,
        ua.browser.family,
        ua.os.family,
    ]

    screen_resolution = request.POST.get('screen_resolution') or request.GET.get('screen_resolution', '')
    if screen_resolution:
        fingerprint_components.append(screen_resolution)

    features = []
    if hasattr(request, 'device_features'):
        features.extend(request.device_features)

    if features:
        fingerprint_components.extend(sorted(features))

    fingerprint_string = '|'.join(str(c) for c in fingerprint_components)
    fingerprint_hash = hashlib.sha256(fingerprint_string.encode()).hexdigest()

    fingerprint_data = {
        'browser_name': ua.browser.family or 'Unknown',
        'browser_version': ua.browser.version_string or '',
        'os_name': ua.os.family or 'Unknown',
        'os_version': ua.os.version_string or '',
        'device_family': ua.device.family or 'Unknown',
        'is_mobile': ua.is_mobile,
        'is_tablet': ua.is_tablet,
        'is_pc': ua.is_pc,
        'is_bot': ua.is_bot,
        'screen_resolution': screen_resolution,
        'features': features,
    }

    return fingerprint_hash, fingerprint_data


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_device_session(user, store, request, store_device=None):
    """
    Create a new device session for a user login safely.
    """
    session = None
    # FIX: Initialize ip_address and fingerprint_data before the try block
    # so they are always bound even if the try block raises early.
    ip_address = get_client_ip(request)
    fingerprint_hash = ''
    fingerprint_data = {}

    try:
        fingerprint_hash, fingerprint_data = generate_device_fingerprint(request)

        latitude, longitude, accuracy, timezone_str = get_location_from_request(request)

        screen_resolution = request.POST.get('screen_resolution') or request.GET.get('screen_resolution', '')

        is_new_device = not DeviceFingerprint.objects.filter(
            user=user,
            fingerprint_hash=fingerprint_hash
        ).exists()

        active_sessions = UserDeviceSession.objects.filter(
            user=user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).count()

        if not validate_store_access(user, store, action='view', raise_exception=False):
            logger.warning(f"User {user} does not have access to store {store}")
            store = None

        if store_device and getattr(store_device, 'is_at_capacity', False):
            logger.warning(f"Device {store_device} at capacity, skipping assignment")
            store_device = None

        session_kwargs = {
            'user': user,
            'store': store,
            'store_device': store_device,
            'session_key': f"{user.id}_{uuid.uuid4().hex}",
            'device_fingerprint': fingerprint_hash,
            'browser_name': fingerprint_data.get('browser_name', ''),
            'browser_version': fingerprint_data.get('browser_version', ''),
            'os_name': fingerprint_data.get('os_name', ''),
            'os_version': fingerprint_data.get('os_version', ''),
            'ip_address': ip_address,
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'screen_resolution': screen_resolution,
            'is_new_device': is_new_device,
            'metadata': fingerprint_data,
        }

        optional_fields = {
            'latitude': latitude,
            'longitude': longitude,
            'location_accuracy': accuracy,
            'timezone': timezone_str,
        }
        for field, value in optional_fields.items():
            try:
                UserDeviceSession._meta.get_field(field)
                if value is not None:
                    session_kwargs[field] = value
            except Exception:
                continue

        session = UserDeviceSession.objects.create(**session_kwargs)

    except Exception as e:
        logger.error(f"Failed to create device session for user {user.email}: {e}")

    # Create device operator log — ip_address is always bound now
    try:
        if session:
            DeviceOperatorLog.objects.create(
                user=user,
                action='LOGIN',
                device=store_device,
                store=store,
                session=session,
                ip_address=ip_address,
                details={
                    'fingerprint': fingerprint_hash,
                    'browser': f"{fingerprint_data.get('browser_name', 'Unknown')} {fingerprint_data.get('browser_version', '')}",
                    'os': f"{fingerprint_data.get('os_name', 'Unknown')} {fingerprint_data.get('os_version', '')}",
                    'is_new_device': getattr(session, 'is_new_device', False),
                    'active_sessions_count': UserDeviceSession.objects.filter(
                        user=user, is_active=True, expires_at__gt=timezone.now()
                    ).count(),
                    'store_device': getattr(store_device, 'name', None),
                },
                success=True
            )
    except Exception as e:
        logger.error(f"Error creating device operator log: {e}")

    # Update or create device fingerprint
    try:
        if fingerprint_hash:
            device_fp, created = DeviceFingerprint.objects.get_or_create(
                user=user,
                fingerprint_hash=fingerprint_hash,
                defaults={
                    'device_name': f"{fingerprint_data.get('browser_name', 'Unknown')} on {fingerprint_data.get('os_name', 'Unknown')}",
                    'browser_name': fingerprint_data.get('browser_name', ''),
                    'os_name': fingerprint_data.get('os_name', ''),
                    'last_ip_address': ip_address,
                    'last_location': (
                        f"{getattr(store, 'name', 'Unknown')}, {getattr(store, 'location', '')}"
                        if store else None
                    ),
                }
            )
            if not created:
                device_fp.last_ip_address = ip_address
                device_fp.last_location = (
                    f"{getattr(store, 'name', 'Unknown')}, {getattr(store, 'location', '')}"
                    if store else device_fp.last_location
                )
                if hasattr(device_fp, 'increment_login'):
                    device_fp.increment_login()
    except Exception as e:
        logger.error(f"Error updating device fingerprint: {e}")

    # Security checks
    try:
        if session:
            create_security_checks(
                user=user,
                store=store,
                session=session,
                store_device=store_device,
                fingerprint_data=fingerprint_data,
                fingerprint_hash=fingerprint_hash,
                ip_address=ip_address,
                latitude=locals().get('latitude'),
                longitude=locals().get('longitude'),
                active_sessions=locals().get('active_sessions', 0),
            )
    except Exception as e:
        logger.error(f"Error creating security checks: {e}")

    if store_device and hasattr(store_device, 'update_last_seen'):
        try:
            store_device.update_last_seen()
        except Exception as e:
            logger.error(f"Error updating device last seen: {e}")

    try:
        if session:
            request.session['device_session_id'] = session.id
            request.session['device_fingerprint'] = fingerprint_hash
            if store:
                request.session['store_id'] = store.id
    except Exception as e:
        logger.error(f"Error storing session data in request.session: {e}")

    return session


def terminate_device_session(session, reason='LOGGED_OUT', request=None):
    """Terminate a device session."""
    ip_address = get_client_ip(request) if request else session.ip_address

    DeviceOperatorLog.objects.create(
        user=session.user,
        action='LOGOUT',
        device=session.store_device,
        store=session.store,
        session=session,
        ip_address=ip_address,
        details={
            'session_duration': str(session.session_duration),
            'reason': reason,
            'last_activity': str(session.last_activity_at),
        },
        success=True
    )

    session.terminate(reason=reason)

    if request:
        request.session.pop('device_session_id', None)
        request.session.pop('device_fingerprint', None)
        request.session.pop('store_id', None)


def get_device_session_from_request(request):
    """Get the current device session from request."""
    session_id = request.session.get('device_session_id')
    if not session_id:
        return None

    try:
        return UserDeviceSession.objects.get(
            id=session_id,
            is_active=True,
            expires_at__gt=timezone.now()
        )
    except UserDeviceSession.DoesNotExist:
        return None


def get_user_active_sessions(user):
    """Get all active sessions for a user."""
    return UserDeviceSession.objects.filter(
        user=user,
        is_active=True,
        expires_at__gt=timezone.now()
    ).select_related('store', 'store_device').order_by('-created_at')


def force_terminate_user_sessions(user, except_session_id=None, terminated_by=None):
    """Force terminate all user sessions except optionally one."""
    sessions = UserDeviceSession.objects.filter(user=user, is_active=True)

    if except_session_id:
        sessions = sessions.exclude(id=except_session_id)

    terminated_count = 0
    for session in sessions:
        DeviceOperatorLog.objects.create(
            user=user,
            action='SESSION_TERMINATED',
            device=session.store_device,
            store=session.store,
            session=session,
            ip_address=session.ip_address,
            details={
                'terminated_by': terminated_by.get_full_name() if terminated_by else 'System',
                'terminated_by_id': terminated_by.id if terminated_by else None,
                'reason': 'Force terminated by admin',
                'session_created': str(session.created_at),
                'session_duration': str(session.session_duration),
            },
            success=True
        )
        session.terminate(reason='FORCE_CLOSED')
        terminated_count += 1

    return terminated_count


def check_and_cleanup_expired_sessions():
    """Clean up expired sessions (run this as a scheduled task)."""
    expired_sessions = UserDeviceSession.objects.filter(
        is_active=True,
        expires_at__lte=timezone.now()
    )

    count = expired_sessions.count()

    for session in expired_sessions:
        session.terminate(reason='EXPIRED')

    return count


# ---------------------------------------------------------------------------
# Security checks
# ---------------------------------------------------------------------------

def create_security_checks(user, store, session, store_device, fingerprint_data,
                            fingerprint_hash, ip_address, latitude, longitude, active_sessions):
    """Create security checks and alerts for a new session."""

    if session.is_new_device:
        SecurityAlert.objects.create(
            user=user,
            store=store,
            session=session,
            device=store_device,
            alert_type='NEW_DEVICE',
            severity='MEDIUM',
            title=f'New device login for {user.get_full_name()}',
            description=(
                f'User logged in from a new device: '
                f'{fingerprint_data.get("browser_name", "Unknown")} on '
                f'{fingerprint_data.get("os_name", "Unknown")}'
            ),
            ip_address=ip_address,
            alert_data={
                'device_info': fingerprint_data,
                'location': f"{latitude}, {longitude}" if latitude and longitude else None,
                'store': store.name if store else None,
            }
        )

    if active_sessions >= 3:
        SecurityAlert.objects.create(
            user=user,
            store=store,
            session=session,
            device=store_device,
            alert_type='CONCURRENT_SESSIONS_EXCEEDED',
            severity='HIGH',
            title=f'Too many concurrent sessions for {user.get_full_name()}',
            description=f'User has {active_sessions + 1} active sessions. Limit is 3.',
            ip_address=ip_address,
            alert_data={
                'active_sessions': active_sessions + 1,
                'limit': 3,
                'store': store.name if store else None,
            }
        )
        session.flag_suspicious(f'User exceeded concurrent session limit ({active_sessions + 1}/3)')

    check_ip_change_alert(user, store, session, store_device, fingerprint_hash, ip_address)


def check_ip_change_alert(user, store, session, store_device, fingerprint_hash, ip_address):
    """Check for IP address changes and create alert if needed."""
    previous_sessions = UserDeviceSession.objects.filter(
        user=user,
        device_fingerprint=fingerprint_hash
    ).exclude(id=session.id).order_by('-created_at')[:5]

    if previous_sessions.exists():
        last_session = previous_sessions.first()
        if last_session.ip_address != ip_address:
            SecurityAlert.objects.create(
                user=user,
                store=store,
                session=session,
                device=store_device,
                alert_type='IP_CHANGE',
                severity='LOW',
                title=f'IP address changed for {user.get_full_name()}',
                description=(
                    f'Same device, different IP. '
                    f'Previous: {last_session.ip_address}, Current: {ip_address}'
                ),
                ip_address=ip_address,
                alert_data={
                    'previous_ip': last_session.ip_address,
                    'current_ip': ip_address,
                    'device_fingerprint': fingerprint_hash,
                    'store': store.name if store else None,
                }
            )


def detect_suspicious_activity(user, store, timeframe_hours=1):
    """
    Detect suspicious activity patterns for a user.
    Returns: (is_suspicious, reasons)
    """
    suspicious = False
    reasons = []

    time_threshold = timezone.now() - timedelta(hours=timeframe_hours)

    failed_logins = DeviceOperatorLog.objects.filter(
        user=user,
        action='LOGIN',
        success=False,
        timestamp__gte=time_threshold
    ).count()

    if failed_logins >= 3:
        suspicious = True
        reasons.append(f'{failed_logins} failed login attempts in the last {timeframe_hours} hour(s)')

    recent_ips = UserDeviceSession.objects.filter(
        user=user,
        created_at__gte=time_threshold
    ).values('ip_address').distinct()

    if recent_ips.count() >= 3:
        suspicious = True
        reasons.append(f'Logins from {recent_ips.count()} different IP addresses in {timeframe_hours} hour(s)')

    new_devices = UserDeviceSession.objects.filter(
        user=user,
        is_new_device=True,
        created_at__gte=time_threshold
    ).count()

    if new_devices >= 2:
        suspicious = True
        reasons.append(f'{new_devices} new devices in {timeframe_hours} hour(s)')

    unusual_stores = 0
    if store:
        unusual_stores = UserDeviceSession.objects.filter(
            user=user,
            created_at__gte=time_threshold
        ).values('store').distinct().count()

        if unusual_stores > 2 and not user.is_company_owner and not user.company_admin:
            suspicious = True
            reasons.append(f'Accessed {unusual_stores} different stores in {timeframe_hours} hour(s)')

    if suspicious:
        SecurityAlert.objects.create(
            user=user,
            store=store,
            alert_type='UNUSUAL_ACTIVITY',
            severity='HIGH',
            title=f'Suspicious activity detected for {user.get_full_name()}',
            description='. '.join(reasons),
            alert_data={
                'detection_timeframe_hours': timeframe_hours,
                'failed_logins': failed_logins,
                'unique_ips': recent_ips.count(),
                'new_devices': new_devices,
                'unusual_stores': unusual_stores,
            }
        )

    return suspicious, reasons


def log_device_action(user, store, action, device=None, session=None,
                      request=None, success=True, error_message='',
                      is_efris_related=False, **extra_details):
    """Helper function to log device actions."""
    ip_address = None
    if request:
        ip_address = get_client_ip(request)
        if not session:
            session = get_device_session_from_request(request)

    details = extra_details.copy()

    if store:
        details['store_name'] = store.name
        details['store_id'] = store.id

    return DeviceOperatorLog.objects.create(
        user=user,
        action=action,
        device=device,
        store=store,
        session=session,
        ip_address=ip_address,
        details=details,
        is_efris_related=is_efris_related,
        success=success,
        error_message=error_message
    )


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

def generate_session_report(store=None, user=None, date_from=None, date_to=None):
    """Generate a session activity report."""
    from django.db.models import Count, Avg, ExpressionWrapper, DurationField, Min
    from django.db.models import Max as MaxFunc

    sessions = UserDeviceSession.objects.all()

    if store:
        sessions = sessions.filter(store=store)
    if user:
        sessions = sessions.filter(user=user)
    if date_from:
        sessions = sessions.filter(created_at__gte=date_from)
    if date_to:
        sessions = sessions.filter(created_at__lte=date_to)

    completed_sessions = sessions.filter(logged_out_at__isnull=False)
    avg_duration = None
    if completed_sessions.exists():
        avg_duration = completed_sessions.annotate(
            duration=ExpressionWrapper(F('logged_out_at') - F('created_at'), output_field=DurationField())
        ).aggregate(Avg('duration'))['duration__avg']

    stats = {
        'total_sessions': sessions.count(),
        'active_sessions': sessions.filter(is_active=True, expires_at__gt=timezone.now()).count(),
        'suspicious_sessions': sessions.filter(is_suspicious=True).count(),
        'new_device_sessions': sessions.filter(is_new_device=True).count(),
        'unique_users': sessions.values('user').distinct().count(),
        'unique_stores': sessions.values('store').distinct().count(),
        'unique_devices': sessions.values('device_fingerprint').distinct().count(),
        'sessions_by_browser': list(sessions.values('browser_name').annotate(count=Count('id')).order_by('-count')),
        'sessions_by_os': list(sessions.values('os_name').annotate(count=Count('id')).order_by('-count')),
        'sessions_by_status': list(sessions.values('status').annotate(count=Count('id')).order_by('-count')),
        'sessions_by_store': list(sessions.values('store__name').annotate(count=Count('id')).order_by('-count')),
        'average_session_duration': avg_duration,
        'first_session': sessions.aggregate(Min('created_at'))['created_at__min'],
        'last_session': sessions.aggregate(MaxFunc('created_at'))['created_at__max'],
    }

    return stats


def generate_security_report(store=None, severity=None, date_from=None, date_to=None):
    """Generate a security alerts report."""
    from django.db.models import Count, Min
    from django.db.models import Max as MaxFunc

    alerts = SecurityAlert.objects.all()

    if store:
        alerts = alerts.filter(store=store)
    if severity:
        alerts = alerts.filter(severity=severity)
    if date_from:
        alerts = alerts.filter(created_at__gte=date_from)
    if date_to:
        alerts = alerts.filter(created_at__lte=date_to)

    stats = {
        'total_alerts': alerts.count(),
        'open_alerts': alerts.filter(status='OPEN').count(),
        'resolved_alerts': alerts.filter(status='RESOLVED').count(),
        'false_positive_alerts': alerts.filter(status='FALSE_POSITIVE').count(),
        'by_severity': list(alerts.values('severity').annotate(count=Count('id')).order_by('-count')),
        'by_type': list(alerts.values('alert_type').annotate(count=Count('id')).order_by('-count')),
        'by_status': list(alerts.values('status').annotate(count=Count('id')).order_by('-count')),
        'by_user': list(
            alerts.values('user__username', 'user__email').annotate(count=Count('id')).order_by('-count')[:10]
        ),
        'by_store': list(alerts.values('store__name').annotate(count=Count('id')).order_by('-count')),
        'high_severity_open': alerts.filter(severity='HIGH', status='OPEN').count(),
        'critical_severity_open': alerts.filter(severity='CRITICAL', status='OPEN').count(),
        'first_alert': alerts.aggregate(Min('created_at'))['created_at__min'],
        'last_alert': alerts.aggregate(MaxFunc('created_at'))['created_at__max'],
        'avg_resolution_time': None,
    }

    return stats


def get_store_performance_metrics(store, days=30):
    """Get comprehensive performance metrics for a store."""
    from django.db.models import Count, Sum, Avg, ExpressionWrapper, DurationField, Q

    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)

    try:
        inventory_summary = store.get_inventory_summary()
        sales_summary = store.get_sales_summary(days)
        device_summary = store.get_device_summary()

        session_stats = UserDeviceSession.objects.filter(
            store=store,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).aggregate(
            total_sessions=Count('id'),
            unique_users=Count('user', distinct=True),
            suspicious_sessions=Count('id', filter=Q(is_suspicious=True))
        )

        operator_stats = DeviceOperatorLog.objects.filter(
            store=store,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).aggregate(
            total_actions=Count('id'),
            successful_actions=Count('id', filter=Q(success=True)),
            failed_actions=Count('id', filter=Q(success=False)),
            efris_actions=Count('id', filter=Q(is_efris_related=True))
        )

        security_stats = SecurityAlert.objects.filter(
            store=store,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).aggregate(
            total_alerts=Count('id'),
            open_alerts=Count('id', filter=Q(status='OPEN')),
            resolved_alerts=Count('id', filter=Q(status='RESOLVED')),
            high_severity_alerts=Count('id', filter=Q(severity='HIGH')),
            critical_severity_alerts=Count('id', filter=Q(severity='CRITICAL'))
        )

        return {
            'period': {'days': days, 'start_date': start_date, 'end_date': end_date},
            'inventory': inventory_summary,
            'sales': sales_summary,
            'devices': device_summary,
            'sessions': session_stats,
            'operations': operator_stats,
            'security': security_stats,
            'staff': {
                'total_staff': store.get_staff_count(),
                'total_managers': store.store_managers.count(),
            },
            'efris': {
                'status': store.efris_status,
                'can_fiscalize': store.can_fiscalize,
                'last_sync': store.efris_last_sync,
                'auto_fiscalize': store.auto_fiscalize_sales,
            },
            'operational': {
                'is_active': store.is_active,
                'allows_sales': store.allows_sales,
                'allows_inventory': store.allows_inventory,
                'is_main_branch': store.is_main_branch,
                'is_open_now': store.is_open_now(),
            }
        }

    except Exception as e:
        logger.error(f"Error getting performance metrics: {str(e)}")
        return {
            'period': {'days': days, 'start_date': start_date, 'end_date': end_date},
            'inventory': store.get_inventory_summary() if hasattr(store, 'get_inventory_summary') else {},
            'sales': store.get_sales_summary(days) if hasattr(store, 'get_sales_summary') else {},
            'devices': store.get_device_summary() if hasattr(store, 'get_device_summary') else {},
            'error': str(e)
        }