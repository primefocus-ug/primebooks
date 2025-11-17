import hashlib
import uuid
from user_agents import parse
from django.utils import timezone
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.db.models.signals import post_save
from datetime import timedelta
from django.db.models import Q, Count, Sum, F,Max
from .models import Store


def get_user_accessible_stores(user, include_inactive=False):
    """
    Get stores accessible to the user based on their role.

    Args:
        user: CustomUser instance
        include_inactive: Whether to include inactive stores

    Returns:
        QuerySet of Store objects
    """
    # SaaS admins can access everything
    if user.is_saas_admin or user.can_access_all_companies:
        queryset = Store.objects.all()

    # Company owners/admins can access all stores in their company
    elif user.is_company_owner:
        queryset = Store.objects.filter(company=user.company)

    # Check role-based permissions
    elif user.primary_role:
        priority = user.primary_role.priority

        # High-level roles (Manager+) can access all company stores
        if priority >= 70:  # Manager level and above
            queryset = Store.objects.filter(company=user.company)

        # Mid-level roles can only access assigned stores
        elif priority >= 40:  # Staff level
            queryset = user.stores.all()

        # Low-level roles have limited access
        else:
            queryset = user.stores.filter(
                # Add additional restrictions for low-level roles
                is_active=True
            )

    # Users without roles - no access
    else:
        queryset = Store.objects.none()

    # Filter by active status if requested
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    return queryset.select_related('company').distinct()


def get_visible_users_for_store(store, requesting_user):
    """
    Get visible users for a specific store, respecting hierarchy.

    Args:
        store: Store instance
        requesting_user: CustomUser making the request

    Returns:
        QuerySet of CustomUser objects
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Base queryset - users in the store
    queryset = store.staff.filter(
        is_active=True,
        is_hidden=False  # Exclude SaaS admins
    )

    # Apply role-based filtering
    if not requesting_user.is_saas_admin:
        # Only show users with equal or lower role priority
        if requesting_user.primary_role:
            max_priority = requesting_user.highest_role_priority

            queryset = queryset.annotate(
                max_role_priority=Max('groups__role__priority')
            ).filter(
                Q(max_role_priority__lte=max_priority) |
                Q(max_role_priority__isnull=True)
            )

    return queryset.select_related('company', 'primary_role__group').distinct()


def filter_stores_by_permissions(user, queryset=None, action='view'):
    """
    Filter stores based on user permissions for specific actions.

    Args:
        user: CustomUser instance
        queryset: Optional base queryset (defaults to all stores)
        action: Permission action ('view', 'change', 'delete', etc.)

    Returns:
        Filtered QuerySet
    """
    if queryset is None:
        queryset = Store.objects.all()

    # SaaS admins have full access
    if user.is_saas_admin:
        return queryset

    # Check specific permission
    perm = f'stores.{action}_store'
    if not user.has_perm(perm):
        return Store.objects.none()

    # Company-level filtering
    if user.company:
        queryset = queryset.filter(company=user.company)
    else:
        return Store.objects.none()

    # Role-based filtering for sensitive actions
    if action in ['delete', 'change']:
        if user.primary_role and user.primary_role.priority < 70:
            # Only managers and above can modify
            return Store.objects.none()

    return queryset


def get_stores_with_statistics(user, store_ids=None):
    """
    Get stores with pre-calculated statistics, filtered by user access.

    Args:
        user: CustomUser instance
        store_ids: Optional list of specific store IDs to include

    Returns:
        QuerySet with annotations
    """
    queryset = get_user_accessible_stores(user)

    if store_ids:
        queryset = queryset.filter(id__in=store_ids)

    return queryset.annotate(
        inventory_count=Count('inventory_items'),
        low_stock_count=Count(
            'inventory_items',
            filter=Q(inventory_items__quantity__lte=F('inventory_items__low_stock_threshold'))
        ),
        total_inventory_value=Sum(
            F('inventory_items__quantity') * F('inventory_items__product__cost_price')
        ),
        device_count=Count('devices', filter=Q(devices__is_active=True)),
        staff_count=Count('staff', filter=Q(staff__is_active=True, staff__is_hidden=False))
    )


def validate_store_access(user, store, action='view', raise_exception=True):
    """
    Validate if user has access to a specific store for a given action.

    Args:
        user: CustomUser instance
        store: Store instance
        action: Permission action string
        raise_exception: Whether to raise exception or return boolean

    Returns:
        Boolean if raise_exception=False, otherwise raises exception

    Raises:
        PermissionDenied if access is denied and raise_exception=True
    """
    from django.core.exceptions import PermissionDenied

    # SaaS admins always have access
    if user.is_saas_admin or user.can_access_all_companies:
        return True

    # Check company match
    if store.company_id != user.company_id:
        if raise_exception:
            raise PermissionDenied("You don't have access to this store's company")
        return False

    # Check permission
    perm = f'stores.{action}_store'
    if not user.has_perm(perm):
        if raise_exception:
            raise PermissionDenied(f"You don't have permission to {action} stores")
        return False

    # Check role-based access for specific actions
    if action in ['delete', 'change']:
        if not user.primary_role or user.primary_role.priority < 70:
            if raise_exception:
                raise PermissionDenied("Insufficient role privileges for this action")
            return False

    return True


def filter_session_queryset(user, base_queryset=None):
    """
    Filter device sessions based on user access.

    Args:
        user: CustomUser instance
        base_queryset: Optional base queryset

    Returns:
        Filtered QuerySet
    """
    from .models import UserDeviceSession

    if base_queryset is None:
        base_queryset = UserDeviceSession.objects.all()

    # Get accessible stores
    accessible_stores = get_user_accessible_stores(user)

    # Filter sessions
    queryset = base_queryset.filter(
        store__in=accessible_stores,
        user__is_hidden=False  # Exclude SaaS admin sessions
    )

    # For non-admins, only show their own sessions unless they're managers
    if not user.is_saas_admin and not user.is_company_owner:
        if user.primary_role and user.primary_role.priority < 70:
            queryset = queryset.filter(user=user)

    return queryset.select_related('user', 'store', 'store_device')


def filter_security_alerts(user, base_queryset=None):
    """
    Filter security alerts based on user access.

    Args:
        user: CustomUser instance
        base_queryset: Optional base queryset

    Returns:
        Filtered QuerySet
    """
    from .models import SecurityAlert

    if base_queryset is None:
        base_queryset = SecurityAlert.objects.all()

    # Get accessible stores
    accessible_stores = get_user_accessible_stores(user)

    # Filter alerts
    queryset = base_queryset.filter(
        store__in=accessible_stores,
        user__is_hidden=False  # Exclude SaaS admin alerts
    )

    # Filter by severity based on role
    if not user.is_saas_admin and user.primary_role:
        if user.primary_role.priority < 50:  # Low-level roles
            # Only show alerts related to their own actions
            queryset = queryset.filter(user=user)
        elif user.primary_role.priority < 70:  # Mid-level roles
            # Can see alerts for their stores but not critical system alerts
            queryset = queryset.exclude(severity='CRITICAL', alert_type__in=[
                'SYSTEM_BREACH', 'UNAUTHORIZED_ACCESS'
            ])

    return queryset.select_related('user', 'store', 'session', 'device')

def generate_device_fingerprint(request):
    """
    Generate a unique device fingerprint from request data
    Returns: (fingerprint_hash, fingerprint_data)
    """
    # Collect device information
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = get_client_ip(request)

    # Parse user agent
    ua = parse(user_agent)

    # Create fingerprint components
    fingerprint_components = [
        user_agent,
        ua.browser.family,
        ua.os.family,
        # Don't include IP in fingerprint as it may change
    ]

    # Add screen resolution if available (from JavaScript on frontend)
    screen_resolution = request.POST.get('screen_resolution') or request.GET.get('screen_resolution', '')
    if screen_resolution:
        fingerprint_components.append(screen_resolution)

    # Generate hash
    fingerprint_string = '|'.join(str(c) for c in fingerprint_components)
    fingerprint_hash = hashlib.sha256(fingerprint_string.encode()).hexdigest()

    # Extract detailed device data
    fingerprint_data = {
        'browser_name': ua.browser.family,
        'browser_version': ua.browser.version_string,
        'os_name': ua.os.family,
        'os_version': ua.os.version_string,
        'device_family': ua.device.family,
        'is_mobile': ua.is_mobile,
        'is_tablet': ua.is_tablet,
        'is_pc': ua.is_pc,
        'is_bot': ua.is_bot,
    }

    return fingerprint_hash, fingerprint_data


def get_client_ip(request):
    """Get the client's real IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_location_from_request(request):
    """
    Extract location data from request (if available from frontend)
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

    return latitude, longitude, accuracy, timezone_str


def create_device_session(user, store, request, store_device=None):
    """
    Create a new device session for a user login
    """
    from .models import UserDeviceSession, DeviceFingerprint, SecurityAlert, DeviceOperatorLog

    # Generate fingerprint
    fingerprint_hash, fingerprint_data = generate_device_fingerprint(request)

    # Get IP and location
    ip_address = get_client_ip(request)
    latitude, longitude, accuracy, timezone_str = get_location_from_request(request)

    # Get screen resolution
    screen_resolution = request.POST.get('screen_resolution') or request.GET.get('screen_resolution', '')

    # Check if this is a new device
    is_new_device = not DeviceFingerprint.objects.filter(
        user=user,
        fingerprint_hash=fingerprint_hash
    ).exists()

    # Check concurrent sessions
    active_sessions = UserDeviceSession.objects.filter(
        user=user,
        is_active=True,
        expires_at__gt=timezone.now()
    ).count()

    # Generate unique session key
    session_key = f"{user.id}_{uuid.uuid4().hex}"

    # Create session
    session = UserDeviceSession.objects.create(
        user=user,
        store=store,
        store_device=store_device,
        session_key=session_key,
        device_fingerprint=fingerprint_hash,
        browser_name=fingerprint_data['browser_name'],
        browser_version=fingerprint_data['browser_version'],
        os_name=fingerprint_data['os_name'],
        os_version=fingerprint_data['os_version'],
        ip_address=ip_address,
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        screen_resolution=screen_resolution,
        latitude=latitude,
        longitude=longitude,
        location_accuracy=accuracy,
        is_new_device=is_new_device,
        metadata=fingerprint_data
    )

    # Create login log
    DeviceOperatorLog.objects.create(
        user=user,
        action='LOGIN',
        device=store_device,
        store=store,
        session=session,
        ip_address=ip_address,
        details={
            'fingerprint': fingerprint_hash,
            'browser': f"{fingerprint_data['browser_name']} {fingerprint_data['browser_version']}",
            'os': f"{fingerprint_data['os_name']} {fingerprint_data['os_version']}",
            'is_new_device': is_new_device,
            'active_sessions_count': active_sessions + 1,
        },
        success=True
    )

    # Update or create device fingerprint
    device_fp, created = DeviceFingerprint.objects.get_or_create(
        user=user,
        fingerprint_hash=fingerprint_hash,
        defaults={
            'device_name': f"{fingerprint_data['browser_name']} on {fingerprint_data['os_name']}",
            'browser_name': fingerprint_data['browser_name'],
            'os_name': fingerprint_data['os_name'],
            'last_ip_address': ip_address,
        }
    )

    if not created:
        device_fp.last_ip_address = ip_address
        device_fp.increment_login()

    # Security checks and alerts

    # Alert 1: New device login
    if is_new_device:
        SecurityAlert.objects.create(
            user=user,
            store=store,
            session=session,
            device=store_device,
            alert_type='NEW_DEVICE',
            severity='MEDIUM',
            title=f'New device login for {user.get_full_name()}',
            description=f'User logged in from a new device: {fingerprint_data["browser_name"]} on {fingerprint_data["os_name"]}',
            ip_address=ip_address,
            alert_data={
                'device_info': fingerprint_data,
                'location': f"{latitude}, {longitude}" if latitude and longitude else None,
            }
        )

    # Alert 2: Too many concurrent sessions
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
            }
        )

        # Mark session as suspicious
        session.flag_suspicious(f'User exceeded concurrent session limit ({active_sessions + 1}/3)')

    # Alert 3: Check for IP location change
    previous_sessions = UserDeviceSession.objects.filter(
        user=user,
        device_fingerprint=fingerprint_hash
    ).exclude(id=session.id).order_by('-created_at')[:5]

    if previous_sessions.exists():
        last_session = previous_sessions.first()
        if last_session.ip_address != ip_address:
            # Different IP for same device - could be normal (mobile data, VPN, etc.)
            SecurityAlert.objects.create(
                user=user,
                store=store,
                session=session,
                device=store_device,
                alert_type='IP_CHANGE',
                severity='LOW',
                title=f'IP address changed for {user.get_full_name()}',
                description=f'Same device, different IP. Previous: {last_session.ip_address}, Current: {ip_address}',
                ip_address=ip_address,
                alert_data={
                    'previous_ip': last_session.ip_address,
                    'current_ip': ip_address,
                    'device_fingerprint': fingerprint_hash,
                }
            )

    # Update store device last seen
    if store_device:
        store_device.update_last_seen()

    # Store session key in Django session for easy access
    request.session['device_session_id'] = session.id
    request.session['device_fingerprint'] = fingerprint_hash

    return session


def terminate_device_session(session, reason='LOGGED_OUT', request=None):
    """
    Terminate a device session
    """
    from .models import DeviceOperatorLog

    # Get IP if request available
    ip_address = get_client_ip(request) if request else session.ip_address

    # Create logout log
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
        },
        success=True
    )

    # Terminate session
    session.terminate(reason=reason)


def check_and_cleanup_expired_sessions():
    """
    Clean up expired sessions (run this as a scheduled task)
    """
    from .models import UserDeviceSession

    expired_sessions = UserDeviceSession.objects.filter(
        is_active=True,
        expires_at__lte=timezone.now()
    )

    count = expired_sessions.count()

    for session in expired_sessions:
        session.terminate(reason='EXPIRED')

    return count


def get_user_active_sessions(user):
    """
    Get all active sessions for a user
    """
    from .models import UserDeviceSession

    return UserDeviceSession.objects.filter(
        user=user,
        is_active=True,
        expires_at__gt=timezone.now()
    ).select_related('store', 'store_device').order_by('-created_at')


def force_terminate_user_sessions(user, except_session_id=None, terminated_by=None):
    """
    Force terminate all user sessions except optionally one
    """
    from .models import UserDeviceSession, DeviceOperatorLog

    sessions = UserDeviceSession.objects.filter(
        user=user,
        is_active=True
    )

    if except_session_id:
        sessions = sessions.exclude(id=except_session_id)

    for session in sessions:
        # Create log
        DeviceOperatorLog.objects.create(
            user=user,
            action='SESSION_TERMINATED',
            device=session.store_device,
            store=session.store,
            session=session,
            ip_address=session.ip_address,
            details={
                'terminated_by': terminated_by.get_full_name() if terminated_by else 'System',
                'reason': 'Force terminated by admin',
            },
            success=True
        )

        session.terminate(reason='FORCE_CLOSED')

    return sessions.count()


def detect_suspicious_activity(user, store, timeframe_hours=1):
    """
    Detect suspicious activity patterns for a user
    Returns: (is_suspicious, reasons)
    """
    from .models import DeviceOperatorLog, UserDeviceSession, SecurityAlert

    suspicious = False
    reasons = []

    time_threshold = timezone.now() - timedelta(hours=timeframe_hours)

    # Check 1: Multiple failed logins
    failed_logins = DeviceOperatorLog.objects.filter(
        user=user,
        action='LOGIN',
        success=False,
        timestamp__gte=time_threshold
    ).count()

    if failed_logins >= 3:
        suspicious = True
        reasons.append(f'{failed_logins} failed login attempts in the last {timeframe_hours} hour(s)')

    # Check 2: Logins from multiple IPs in short time
    recent_sessions = UserDeviceSession.objects.filter(
        user=user,
        created_at__gte=time_threshold
    ).values_list('ip_address', flat=True).distinct()

    if recent_sessions.count() >= 3:
        suspicious = True
        reasons.append(f'Logins from {recent_sessions.count()} different IP addresses in {timeframe_hours} hour(s)')

    # Check 3: Multiple new devices
    new_devices = UserDeviceSession.objects.filter(
        user=user,
        is_new_device=True,
        created_at__gte=time_threshold
    ).count()

    if new_devices >= 2:
        suspicious = True
        reasons.append(f'{new_devices} new devices in {timeframe_hours} hour(s)')

    # Create alert if suspicious
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
                'unique_ips': recent_sessions.count(),
                'new_devices': new_devices,
            }
        )

    return suspicious, reasons


def get_device_session_from_request(request):
    """
    Get the current device session from request
    """
    from .models import UserDeviceSession

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


def log_device_action(user, store, action, device=None, session=None,
                      request=None, success=True, error_message='',
                      is_efris_related=False, **extra_details):
    """
    Helper function to log device actions
    """
    from .models import DeviceOperatorLog

    ip_address = None
    if request:
        ip_address = get_client_ip(request)
        if not session:
            session = get_device_session_from_request(request)

    details = extra_details.copy()

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



@receiver(user_logged_in)
def handle_user_login(sender, request, user, **kwargs):
    """
    Automatically create device session on user login
    """
    # Skip for staff/superuser logins to admin
    if request.path.startswith('/admin/'):
        return

    # Get store from request/session (you'll need to implement this based on your setup)
    store = getattr(request, 'store', None)
    if not store:
        # Try to get from session or user's default store
        store = user.company.stores.first() if hasattr(user, 'company') else None

    if not store:
        return

    # Get store device if specified
    store_device = None
    device_id = request.POST.get('store_device_id') or request.GET.get('store_device_id')
    if device_id:
        from .models import StoreDevice
        try:
            store_device = StoreDevice.objects.get(id=device_id, store=store, is_active=True)
        except StoreDevice.DoesNotExist:
            pass

    # Create session
    try:
        create_device_session(user, store, request, store_device)
    except Exception as e:
        # Log error but don't prevent login
        print(f"Error creating device session: {e}")


@receiver(user_logged_out)
def handle_user_logout(sender, request, user, **kwargs):
    """
    Automatically terminate device session on user logout
    """
    if not user:
        return

    session = get_device_session_from_request(request)
    if session:
        try:
            terminate_device_session(session, reason='LOGGED_OUT', request=request)
        except Exception as e:
            print(f"Error terminating device session: {e}")


# Management command helper functions

def generate_session_report(store=None, user=None, date_from=None, date_to=None):
    """
    Generate a session activity report
    """
    from .models import UserDeviceSession
    from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField

    sessions = UserDeviceSession.objects.all()

    if store:
        sessions = sessions.filter(store=store)
    if user:
        sessions = sessions.filter(user=user)
    if date_from:
        sessions = sessions.filter(created_at__gte=date_from)
    if date_to:
        sessions = sessions.filter(created_at__lte=date_to)

    # Calculate statistics
    stats = {
        'total_sessions': sessions.count(),
        'active_sessions': sessions.filter(is_active=True, expires_at__gt=timezone.now()).count(),
        'suspicious_sessions': sessions.filter(is_suspicious=True).count(),
        'new_device_sessions': sessions.filter(is_new_device=True).count(),
        'unique_users': sessions.values('user').distinct().count(),
        'unique_devices': sessions.values('device_fingerprint').distinct().count(),
        'sessions_by_browser': sessions.values('browser_name').annotate(count=Count('id')),
        'sessions_by_os': sessions.values('os_name').annotate(count=Count('id')),
        'sessions_by_status': sessions.values('status').annotate(count=Count('id')),
    }

    return stats


def generate_security_report(store=None, severity=None, date_from=None, date_to=None):
    """
    Generate a security alerts report
    """
    from .models import SecurityAlert
    from django.db.models import Count

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
        'by_severity': alerts.values('severity').annotate(count=Count('id')),
        'by_type': alerts.values('alert_type').annotate(count=Count('id')),
        'by_status': alerts.values('status').annotate(count=Count('id')),
        'high_severity_open': alerts.filter(severity='HIGH', status='OPEN').count(),
        'critical_severity_open': alerts.filter(severity='CRITICAL', status='OPEN').count(),
    }

    return stats