from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from .utils import (
    get_device_session_from_request,
    detect_suspicious_activity,
    get_client_ip
)


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
                SecurityAlert.objects.create(
                    user=request.user,
                    store=session.store,
                    session=session,
                    device=session.store_device,
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

        # Get store from request
        store = getattr(request, 'store', None)
        if not store and hasattr(request.user, 'company'):
            store = request.user.company.stores.first()

        if not store:
            return None

        # Run suspicious activity detection periodically (not on every request)
        # Check if we should run detection (stored in session)
        last_check = request.session.get('last_suspicious_check')
        now = timezone.now().timestamp()

        # Run check every 5 minutes
        if not last_check or (now - last_check) > 300:
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

            store = getattr(request, 'store', None) or (
                request.user.company.stores.first() if hasattr(request.user, 'company') else None
            )

            for session in oldest_sessions:
                # Log the termination
                if store:
                    log_device_action(
                        user=request.user,
                        store=store,
                        action='SESSION_TERMINATED',
                        device=session.store_device,
                        session=session,
                        success=True,
                        reason='Concurrent session limit exceeded',
                        terminated_sessions=active_count
                    )

                session.terminate(reason='FORCE_CLOSED')

        return None