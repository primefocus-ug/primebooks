import hashlib
import uuid
from user_agents import parse
from django.utils import timezone
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.db.models.signals import post_save
from datetime import timedelta
import logging
from django.db.models import Q, Count, Sum, F, Max
from .models import Store, StoreDevice, UserDeviceSession, DeviceFingerprint, SecurityAlert, DeviceOperatorLog

logger=logging.getLogger(__name__)

def get_user_accessible_stores(user, include_inactive=False):
    """
    Get stores accessible by the user based on permissions and company

    ✅ FIXED: Properly combines querysets instead of using union on managers
    """
    from django.db.models import Q

    # SaaS admins can access everything
    if user.is_saas_admin or user.can_access_all_companies:
        queryset = Store.objects.all()

    # Company owners/admins can access all stores in their company
    elif user.is_company_owner or user.company_admin:
        queryset = Store.objects.filter(company=user.company)

    # Regular users: combine multiple access paths
    else:
        # Build a Q object to combine all conditions
        conditions = Q()

        # ✅ FIX: Check if user has stores attribute (related_name from Store.staff)
        # This could be 'stores' or 'assigned_stores' depending on your Store model
        if hasattr(user, 'stores'):
            # Get IDs of stores where user is staff
            staff_store_ids = user.stores.filter(is_active=True).values_list('id', flat=True)
            if staff_store_ids:
                conditions |= Q(id__in=staff_store_ids)

        # Check if user is a store manager
        if hasattr(user, 'managed_stores'):
            managed_store_ids = user.managed_stores.filter(is_active=True).values_list('id', flat=True)
            if managed_store_ids:
                conditions |= Q(id__in=managed_store_ids)

        # Check StoreAccess permissions
        from .models import StoreAccess
        access_store_ids = StoreAccess.objects.filter(
            user=user,
            is_active=True
        ).values_list('store_id', flat=True)
        if access_store_ids:
            conditions |= Q(id__in=access_store_ids)

        # Check if any store in user's company is accessible by all
        if user.company:
            conditions |= Q(
                company=user.company,
                accessible_by_all=True,
                is_active=True
            )

        # Apply combined conditions
        if conditions:
            queryset = Store.objects.filter(conditions)
        else:
            queryset = Store.objects.none()

    # Filter by active status if requested
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    return queryset.select_related('company').distinct()


def get_visible_users_for_store(store, requesting_user):
    """
    Get users visible to the requesting user for a specific store
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Base queryset - users assigned to the store
    queryset = store.staff.filter(
        is_active=True,
        is_hidden=False  # Exclude SaaS admins
    )

    # SaaS admins can see everyone
    if requesting_user.is_saas_admin:
        return queryset

    # Company admins can see all users in their company
    if requesting_user.is_company_owner or requesting_user.company_admin:
        if store.company == requesting_user.company:
            return queryset.select_related('company').distinct()
        return User.objects.none()

    # Store managers can see staff in their stores
    if store.store_managers.filter(id=requesting_user.id).exists():
        return queryset.select_related('company').distinct()

    # Regular staff can only see themselves
    if store.staff.filter(id=requesting_user.id).exists():
        return queryset.filter(id=requesting_user.id)

    return User.objects.none()


def filter_stores_by_permissions(user, queryset=None, action='view'):
    """
    Filter stores based on user permissions for specific actions

    ✅ Uses the corrected get_user_accessible_stores function
    """
    if queryset is None:
        # Use the fixed function
        return get_user_accessible_stores(user)

    # SaaS admins have full access
    if user.is_saas_admin:
        return queryset

    # Get accessible stores
    accessible_stores = get_user_accessible_stores(user)

    # Intersect with provided queryset
    return queryset.filter(id__in=accessible_stores.values_list('id', flat=True))


def get_stores_with_statistics(user, store_ids=None):
    """
    Get stores with statistics for dashboard display
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
    Validate if user has access to a specific store

    ✅ Uses the user's can_access_store method if available
    """
    from django.core.exceptions import PermissionDenied

    # Use the CustomUser method if available
    if hasattr(user, 'can_access_store'):
        has_access = user.can_access_store(store)
        if not has_access and raise_exception:
            raise PermissionDenied("You don't have access to this store")
        return has_access

    # Fallback logic
    # SaaS admins always have access
    if user.is_saas_admin or getattr(user, 'can_access_all_companies', False):
        return True

    # Check company match
    if not store.company or store.company_id != user.company_id:
        if raise_exception:
            raise PermissionDenied("You don't have access to this store's company")
        return False

    # Check permission
    perm = f'stores.{action}_store'
    if not user.has_perm(perm):
        if raise_exception:
            raise PermissionDenied(f"You don't have permission to {action} stores")
        return False

    # Check store-specific access
    if not getattr(store, 'accessible_by_all', False):
        # Check if user is staff or manager
        is_staff = store.staff.filter(id=user.id).exists()
        is_manager = store.store_managers.filter(id=user.id).exists() if hasattr(store, 'store_managers') else False

        if not (is_staff or is_manager):
            if raise_exception:
                raise PermissionDenied("You don't have access to this specific store")
            return False

    # Check role-based access for specific actions
    if action in ['delete', 'change']:
        # Only managers or higher can modify
        is_manager = store.store_managers.filter(id=user.id).exists() if hasattr(store, 'store_managers') else False
        if not (getattr(user, 'is_company_owner', False) or getattr(user, 'company_admin', False) or is_manager):
            if raise_exception:
                raise PermissionDenied("Insufficient privileges for this action")
            return False

    return True


def filter_session_queryset(user, base_queryset=None):
    """
    Filter device sessions based on user permissions
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

    # For non-admins, only show their own sessions unless they're managers/admins
    if not user.is_saas_admin and not getattr(user, 'is_company_owner', False) and not getattr(user, 'company_admin',
                                                                                               False):
        # Store managers can see sessions in their stores
        if hasattr(user, 'managed_stores') and user.managed_stores.exists():
            managed_stores = user.managed_stores.all()
            queryset = queryset.filter(store__in=managed_stores)
        else:
            # Regular staff can only see their own sessions
            queryset = queryset.filter(user=user)

    return queryset.select_related('user', 'store', 'store_device')


def filter_security_alerts(user, base_queryset=None):
    """
    Filter security alerts based on user permissions
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

    # Filter by user role
    if not user.is_saas_admin:
        if getattr(user, 'is_company_owner', False) or getattr(user, 'company_admin', False):
            # Company admins can see all alerts in their company
            pass
        elif hasattr(user, 'managed_stores') and user.managed_stores.exists():
            # Store managers can see alerts in their managed stores
            managed_stores = user.managed_stores.all()
            queryset = queryset.filter(store__in=managed_stores)
        else:
            # Regular staff can only see their own alerts
            queryset = queryset.filter(user=user)

    return queryset.select_related('user', 'store', 'session', 'device')


def get_client_ip(request):
    """Get the client's real IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip




def create_device_session(user, store, request, store_device=None):
    """
    Create a new device session for a user login safely.
    Handles optional fields, missing store/device, and avoids 500 errors.
    """
    from .models import UserDeviceSession

    # Initialize session variable to avoid unbound variable errors
    session = None

    try:
        # Generate device fingerprint
        fingerprint_hash, fingerprint_data = generate_device_fingerprint(request)

        # Get IP and location
        ip_address = get_client_ip(request)
        latitude, longitude, accuracy, timezone_str = get_location_from_request(request)

        # Screen resolution
        screen_resolution = request.POST.get('screen_resolution') or request.GET.get('screen_resolution', '')

        # New device check
        is_new_device = not DeviceFingerprint.objects.filter(
            user=user,
            fingerprint_hash=fingerprint_hash
        ).exists()

        # Active session count
        active_sessions = UserDeviceSession.objects.filter(
            user=user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).count()

        # Validate store access
        if not validate_store_access(user, store, action='view', raise_exception=False):
            logger.warning(f"User {user} does not have access to store {store}")
            store = None

        # Device capacity
        if store_device and getattr(store_device, 'is_at_capacity', False):
            logger.warning(f"Device {store_device} at capacity, skipping assignment")
            store_device = None

        # Base kwargs
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

        # Optional fields: only add if model has field
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
                # Field does not exist, skip
                continue

        # Create session
        session = UserDeviceSession.objects.create(**session_kwargs)

    except Exception as e:
        logger.error(f"Failed to create device session for user {user.email}: {e}")
        # session remains None

    # Create device operator log safely
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
                    'is_new_device': is_new_device,
                    'active_sessions_count': active_sessions + 1,
                    'store_device': getattr(store_device, 'name', None),
                },
                success=True
            )
    except Exception as e:
        logger.error(f"Error creating device operator log: {e}")

    # Update or create device fingerprint
    try:
        device_fp, created = DeviceFingerprint.objects.get_or_create(
            user=user,
            fingerprint_hash=fingerprint_hash,
            defaults={
                'device_name': f"{fingerprint_data.get('browser_name', 'Unknown')} on {fingerprint_data.get('os_name', 'Unknown')}",
                'browser_name': fingerprint_data.get('browser_name', ''),
                'os_name': fingerprint_data.get('os_name', ''),
                'last_ip_address': ip_address,
                'last_location': f"{getattr(store, 'name', 'Unknown')}, {getattr(store, 'location', '')}" if store else None,
            }
        )
        if not created:
            device_fp.last_ip_address = ip_address
            device_fp.last_location = f"{getattr(store, 'name', 'Unknown')}, {getattr(store, 'location', '')}" if store else device_fp.last_location
            if hasattr(device_fp, 'increment_login'):
                device_fp.increment_login()
    except Exception as e:
        logger.error(f"Error updating device fingerprint: {e}")

    # Security checks - FIXED: Pass all required arguments
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
                latitude=latitude,
                longitude=longitude,
                active_sessions=active_sessions
            )
    except Exception as e:
        logger.error(f"Error creating security checks: {e}")

    # Update store device last seen
    if store_device and hasattr(store_device, 'update_last_seen'):
        try:
            store_device.update_last_seen()
        except Exception as e:
            logger.error(f"Error updating device last seen: {e}")

    # Store session info in Django session safely
    try:
        if session:
            request.session['device_session_id'] = session.id
            request.session['device_fingerprint'] = fingerprint_hash
            if store:
                request.session['store_id'] = store.id
    except Exception as e:
        logger.error(f"Error storing session data in request.session: {e}")

    return session

def generate_device_fingerprint(request):
    """
    Generate a unique device fingerprint from request data
    Returns: (fingerprint_hash, fingerprint_data)
    """
    # Collect device information
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = get_client_ip(request)

    # Parse user agent
    try:
        ua = parse(user_agent)
    except Exception as e:
        logger.error(f"Error parsing user agent: {e}")
        # Return basic fingerprint
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

    # Create fingerprint components
    fingerprint_components = [
        user_agent,
        ua.browser.family,
        ua.os.family,
    ]

    # Add screen resolution if available (from JavaScript on frontend)
    screen_resolution = request.POST.get('screen_resolution') or request.GET.get('screen_resolution', '')
    if screen_resolution:
        fingerprint_components.append(screen_resolution)

    # Add device features if available
    features = []
    if hasattr(request, 'device_features'):
        features.extend(request.device_features)

    if features:
        fingerprint_components.extend(sorted(features))

    # Generate hash
    fingerprint_string = '|'.join(str(c) for c in fingerprint_components)
    fingerprint_hash = hashlib.sha256(fingerprint_string.encode()).hexdigest()

    # Extract detailed device data
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

    return latitude, longitude, accuracy, timezone_str or 'UTC'


@receiver(user_logged_in)
def handle_user_login(sender, request, user, **kwargs):
    """
    Automatically create device session on user login
    """
    # Skip for staff/superuser logins to admin
    if request.path.startswith('/admin/'):
        return

    # Skip for SaaS admins to avoid issues
    if getattr(user, 'is_saas_admin', False):
        return

    # Get store from request/session
    store = getattr(request, 'store', None)
    if not store:
        # Try to get store ID from session
        store_id = request.session.get('store_id') or request.POST.get('store_id') or request.GET.get('store_id')
        if store_id:
            try:
                store = Store.objects.get(id=store_id, is_active=True)
            except Store.DoesNotExist:
                store = None

        # If still no store, try user's default store
        if not store and hasattr(user, 'get_accessible_stores'):
            try:
                accessible_stores = user.get_accessible_stores()
                store = accessible_stores.first()
            except Exception as e:
                logger.error(f"Error getting accessible stores: {e}")
                return
        elif not store and hasattr(user, 'company'):
            try:
                store = Store.objects.filter(
                    company=user.company,
                    is_active=True
                ).first()
            except Exception as e:
                logger.error(f"Error getting company store: {e}")
                return

    if not store:
        # No store available, skip session creation
        return

    # Check if user has access to the store
    try:
        if not validate_store_access(user, store, action='view', raise_exception=False):
            # User doesn't have access to this store
            return
    except Exception as e:
        logger.error(f"Error validating store access: {e}")
        return

    # Get store device if specified
    store_device = None
    device_id = request.POST.get('store_device_id') or request.GET.get('store_device_id')
    if device_id:
        try:
            store_device = StoreDevice.objects.get(id=device_id, store=store, is_active=True)
        except StoreDevice.DoesNotExist:
            pass

    # Create session
    try:
        create_device_session(user, store, request, store_device)
    except Exception as e:
        # Log error but don't prevent login
        logger.error(f"Error creating device session: {e}")


@receiver(user_logged_out)
def handle_user_logout(sender, request, user, **kwargs):
    """
    Automatically terminate device session on user logout
    """
    if not user:
        return

    try:
        session = get_device_session_from_request(request)
        if session:
            terminate_device_session(session, reason='LOGGED_OUT', request=request)
    except Exception as e:
        logger.error(f"Error terminating device session: {e}")

###===##

def create_security_checks(user, store, session, store_device, fingerprint_data,
                          fingerprint_hash, ip_address, latitude, longitude, active_sessions):
    """
    Create security checks and alerts for a new session
    """
    # Alert 1: New device login
    if session.is_new_device:
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
                'store': store.name if store else None,  # Also add safety check here
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
                'store': store.name if store else None,  # Add safety check here too
            }
        )

        # Mark session as suspicious
        session.flag_suspicious(f'User exceeded concurrent session limit ({active_sessions + 1}/3)')

    # Alert 3: Check for IP location change
    check_ip_change_alert(user, store, session, store_device, fingerprint_hash, ip_address)


def check_ip_change_alert(user, store, session, store_device, fingerprint_hash, ip_address):
    """
    Check for IP address changes and create alert if needed
    """
    previous_sessions = UserDeviceSession.objects.filter(
        user=user,
        device_fingerprint=fingerprint_hash
    ).exclude(id=session.id).order_by('-created_at')[:5]

    if previous_sessions.exists():
        last_session = previous_sessions.first()
        if last_session.ip_address != ip_address:
            # Different IP for same device
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
                    'store': store.name if store else None,  # Add safety check
                }
            )

def terminate_device_session(session, reason='LOGGED_OUT', request=None):
    """
    Terminate a device session
    """
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
            'last_activity': session.last_activity_at,
        },
        success=True
    )

    # Terminate session
    session.terminate(reason=reason)

    # Clear session data from request if available
    if request:
        request.session.pop('device_session_id', None)
        request.session.pop('device_fingerprint', None)
        request.session.pop('store_id', None)


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

    terminated_count = 0
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
                'terminated_by_id': terminated_by.id if terminated_by else None,
                'reason': 'Force terminated by admin',
                'session_created': session.created_at,
                'session_duration': str(session.session_duration),
            },
            success=True
        )

        session.terminate(reason='FORCE_CLOSED')
        terminated_count += 1

    return terminated_count


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

    # Check 4: Unusual store access patterns
    if store:
        unusual_stores = UserDeviceSession.objects.filter(
            user=user,
            created_at__gte=time_threshold
        ).values('store').distinct().count()

        if unusual_stores > 2 and not user.is_company_owner and not user.company_admin:
            suspicious = True
            reasons.append(f'Accessed {unusual_stores} different stores in {timeframe_hours} hour(s)')

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
                'unusual_stores': unusual_stores if 'unusual_stores' in locals() else 0,
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

    # Add store info if available
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


@receiver(user_logged_in)
def handle_user_login(sender, request, user, **kwargs):
    """
    Automatically create device session on user login
    """
    # Skip for staff/superuser logins to admin
    if request.path.startswith('/admin/'):
        return

    # Get store from request/session
    store = getattr(request, 'store', None)
    if not store:
        # Try to get store ID from session
        store_id = request.session.get('store_id') or request.POST.get('store_id') or request.GET.get('store_id')
        if store_id:
            try:
                store = Store.objects.get(id=store_id, is_active=True)
            except Store.DoesNotExist:
                store = None

        # If still no store, try user's default store
        if not store and hasattr(user, 'company'):
            store = user.company.stores.filter(is_active=True).first()

    if not store:
        return

    # Check if user has access to the store
    try:
        validate_store_access(user, store, action='view', raise_exception=True)
    except:
        # User doesn't have access to this store
        return

    # Get store device if specified
    store_device = None
    device_id = request.POST.get('store_device_id') or request.GET.get('store_device_id')
    if device_id:
        try:
            store_device = StoreDevice.objects.get(id=device_id, store=store, is_active=True)
        except StoreDevice.DoesNotExist:
            pass

    # Create session
    try:
        create_device_session(user, store, request, store_device)
    except Exception as e:
        # Log error but don't prevent login
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error creating device session: {e}")


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
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error terminating device session: {e}")


# Management command helper functions

def generate_session_report(store=None, user=None, date_from=None, date_to=None):
    """
    Generate a session activity report
    """
    from .models import UserDeviceSession
    from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField, Min, Max as MaxFunc

    sessions = UserDeviceSession.objects.all()

    if store:
        sessions = sessions.filter(store=store)
    if user:
        sessions = sessions.filter(user=user)
    if date_from:
        sessions = sessions.filter(created_at__gte=date_from)
    if date_to:
        sessions = sessions.filter(created_at__lte=date_to)

    # Calculate duration for completed sessions
    completed_sessions = sessions.filter(logged_out_at__isnull=False)
    avg_duration = None
    if completed_sessions.exists():
        avg_duration = completed_sessions.annotate(
            duration=ExpressionWrapper(F('logged_out_at') - F('created_at'), output_field=DurationField())
        ).aggregate(Avg('duration'))['duration__avg']

    # Calculate statistics
    stats = {
        'total_sessions': sessions.count(),
        'active_sessions': sessions.filter(is_active=True, expires_at__gt=timezone.now()).count(),
        'suspicious_sessions': sessions.filter(is_suspicious=True).count(),
        'new_device_sessions': sessions.filter(is_new_device=True).count(),
        'unique_users': sessions.values('user').distinct().count(),
        'unique_stores': sessions.values('store').distinct().count(),
        'unique_devices': sessions.values('device_fingerprint').distinct().count(),
        'sessions_by_browser': sessions.values('browser_name').annotate(count=Count('id')).order_by('-count'),
        'sessions_by_os': sessions.values('os_name').annotate(count=Count('id')).order_by('-count'),
        'sessions_by_status': sessions.values('status').annotate(count=Count('id')).order_by('-count'),
        'sessions_by_store': sessions.values('store__name').annotate(count=Count('id')).order_by('-count'),
        'average_session_duration': avg_duration,
        'first_session': sessions.aggregate(Min('created_at'))['created_at__min'],
        'last_session': sessions.aggregate(MaxFunc('created_at'))['created_at__max'],
    }

    return stats


def generate_security_report(store=None, severity=None, date_from=None, date_to=None):
    """
    Generate a security alerts report
    """
    from .models import SecurityAlert
    from django.db.models import Count, Min, Max as MaxFunc

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
        'by_severity': alerts.values('severity').annotate(count=Count('id')).order_by('-count'),
        'by_type': alerts.values('alert_type').annotate(count=Count('id')).order_by('-count'),
        'by_status': alerts.values('status').annotate(count=Count('id')).order_by('-count'),
        'by_user': alerts.values('user__username', 'user__email').annotate(count=Count('id')).order_by('-count')[:10],
        'by_store': alerts.values('store__name').annotate(count=Count('id')).order_by('-count'),
        'high_severity_open': alerts.filter(severity='HIGH', status='OPEN').count(),
        'critical_severity_open': alerts.filter(severity='CRITICAL', status='OPEN').count(),
        'first_alert': alerts.aggregate(Min('created_at'))['created_at__min'],
        'last_alert': alerts.aggregate(MaxFunc('created_at'))['created_at__max'],
        'avg_resolution_time': None,  # This would require additional calculation
    }

    return stats


def get_store_performance_metrics(store, days=30):
    """
    Get comprehensive performance metrics for a store
    """
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Count, Sum, Avg, Min, Max, ExpressionWrapper, DurationField, F, Q

    # Get date range
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)

    try:
        # Get store statistics
        inventory_summary = store.get_inventory_summary()
        sales_summary = store.get_sales_summary(days)
        device_summary = store.get_device_summary()

        # Get session statistics for the period
        session_stats = UserDeviceSession.objects.filter(
            store=store,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).aggregate(
            total_sessions=Count('id'),
            unique_users=Count('user', distinct=True),
            suspicious_sessions=Count('id', filter=Q(is_suspicious=True))
        )

        # Get operator log statistics
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

        # Get security alerts
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

        metrics = {
            'period': {
                'days': days,
                'start_date': start_date,
                'end_date': end_date
            },
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

        return metrics

    except Exception as e:
        logger.error(f"Error getting performance metrics: {str(e)}")
        # Return basic metrics without the problematic calculations
        return {
            'period': {
                'days': days,
                'start_date': start_date,
                'end_date': end_date
            },
            'inventory': store.get_inventory_summary() if hasattr(store, 'get_inventory_summary') else {},
            'sales': store.get_sales_summary(days) if hasattr(store, 'get_sales_summary') else {},
            'devices': store.get_device_summary() if hasattr(store, 'get_device_summary') else {},
            'error': str(e)
        }