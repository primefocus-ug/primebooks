from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from functools import wraps
from user_agents import parse
import requests
from django.core.cache import cache
import time

User = get_user_model()


def get_visible_users(queryset=None, company=None):
    if queryset is None:
        queryset = User.objects.all()

    # Filter out hidden users
    queryset = queryset.filter(is_hidden=False)

    # Filter by company if specified
    if company:
        queryset = queryset.filter(company=company)

    return queryset


def get_company_user_count(company, active_only=True):
    queryset = User.objects.filter(company=company, is_hidden=False)

    if active_only:
        queryset = queryset.filter(is_active=True)

    return queryset.count()


def get_accessible_companies(user):
    from company.models import Company

    if not user.is_authenticated:
        return Company.objects.none()

    if getattr(user, 'is_saas_admin', False) or getattr(user, 'can_access_all_companies', False):
        return Company.objects.all()

    if hasattr(user, 'company') and user.company:
        return Company.objects.filter(pk=user.company.pk)  # ✅ use pk, works with company_id

    return Company.objects.none()



def can_access_company(user, company):
    if not user.is_authenticated:
        return False

    if getattr(user, 'is_saas_admin', False):
        return True

    if getattr(user, 'can_access_all_companies', False):
        return True

    if hasattr(user, 'company') and user.company:
        return user.company.company_id == company.company_id

    return False


def require_saas_admin(view_func):

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")

        if not getattr(request.user, 'is_saas_admin', False):
            raise PermissionDenied("SaaS admin permissions required")

        return view_func(request, *args, **kwargs)

    return wrapper


def require_company_access(company_param='company_id'):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required")

            # Get company ID from kwargs
            company_id = kwargs.get(company_param)
            if not company_id:
                raise PermissionDenied("Company ID required")

            # Get company instance
            try:
                from company.models import Company
                company = Company.objects.get(company_id=company_id)
            except Company.DoesNotExist:
                raise PermissionDenied("Company not found")

            # Check access
            if not can_access_company(request.user, company):
                raise PermissionDenied("You don't have access to this company")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def create_company_default_admin(company, admin_email=None, admin_password=None):
    if not admin_email:
        admin_email = f"admin@{company.schema_name}.com"

    if not admin_password:
        import secrets
        admin_password = secrets.token_urlsafe(12)

    # Check if admin already exists
    existing_admin = User.objects.filter(
        company=company,
    ).first()

    if existing_admin:
        return existing_admin

    # Create company admin
    admin_user = User.objects.create_user(
        email=admin_email,
        password=admin_password,
        username=f"{company.schema_name}_admin",
        first_name="Company",
        last_name="Admin",
        company=company,
        company_admin=True,
        is_staff=True
    )

    return admin_user


def ensure_saas_admin_exists():
    """
    Ensure at least one SaaS admin exists in the system

    Returns:
        User instance of a SaaS admin or None if creation failed
    """
    # Check if any SaaS admin exists
    saas_admin = User.objects.filter(is_saas_admin=True).first()

    if saas_admin:
        return saas_admin

    # Create default SaaS admin
    try:
        from django.conf import settings

        saas_admin = User.objects.create_saas_admin(
            email=getattr(settings, 'DEFAULT_SAAS_ADMIN_EMAIL', 'admin@saas.com'),
            password=getattr(settings, 'DEFAULT_SAAS_ADMIN_PASSWORD', 'saas_admin_2024'),
            username='saas_admin',
            first_name='SaaS',
            last_name='Administrator'
        )

        print(f"Created default SaaS admin: {saas_admin.email}")
        return saas_admin

    except Exception as e:
        print(f"Could not create SaaS admin: {str(e)}")
        return None



def get_client_ip(request):
    """
    Extract client IP address from request
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def parse_user_agent(user_agent_string):
    """
    Parse user agent string to extract browser, OS, and device info
    """
    user_agent = parse(user_agent_string)

    return {
        'browser': f"{user_agent.browser.family} {user_agent.browser.version_string}",
        'os': f"{user_agent.os.family} {user_agent.os.version_string}",
        'device_type': 'Mobile' if user_agent.is_mobile else ('Tablet' if user_agent.is_tablet else 'Desktop'),
        'device_brand': user_agent.device.brand or '',
        'device_model': user_agent.device.model or ''
    }


def build_device_fingerprint_server_side(request) -> str:
    """
    Build a lightweight device fingerprint from server-visible headers.
    Used as a fallback when FingerprintJS data is not posted by the client.

    For best accuracy, include FingerprintJS in your login template and POST
    the visitorId as a hidden field named 'fp'.  This fallback is still
    useful: it differentiates most distinct browser/OS/language combinations.
    """
    import hashlib
    ua = request.META.get('HTTP_USER_AGENT', '')
    lang = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    encoding = request.META.get('HTTP_ACCEPT_ENCODING', '')
    raw = f"{ua}:{lang}:{encoding}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_location_from_ip(ip_address):
    """
    Get approximate location from IP address using free API
    Cache results to avoid repeated API calls
    """
    # Check cache first
    cache_key = f'ip_location_{ip_address}'
    cached_location = cache.get(cache_key)

    if cached_location:
        return cached_location

    # Skip for local/private IPs
    if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith('192.168.'):
        return None

    try:
        # Using ip-api.com (free tier: 45 requests/minute)
        response = requests.get(
            f'http://ip-api.com/json/{ip_address}',
            timeout=3
        )

        if response.status_code == 200:
            data = response.json()

            if data.get('status') == 'success':
                location_data = {
                    'city': data.get('city', ''),
                    'region': data.get('regionName', ''),
                    'country': data.get('country', ''),
                    'latitude': data.get('lat'),
                    'longitude': data.get('lon'),
                    'timezone': data.get('timezone', ''),
                    'isp': data.get('isp', '')
                }

                # Cache for 24 hours
                cache.set(cache_key, location_data, 86400)
                return location_data

    except Exception as e:
        # Log error but don't fail
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to get location for IP {ip_address}: {e}")

    return None


def log_action(request, action, description, **kwargs):

    from .models import AuditLog

    return AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        action_description=description,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        request_path=request.path,
        request_method=request.method,
        duration_ms=getattr(request, '_audit_duration', None),
        company=getattr(request.user, 'company', None) if request.user.is_authenticated else None,
        store=getattr(request, 'store', None),
        **kwargs
    )


def track_model_changes(old_instance, new_instance, fields=None):

    changes = {}

    if fields is None:
        fields = [f.name for f in new_instance._meta.fields
                  if not f.name in ['id', 'created_at', 'updated_at']]

    for field in fields:
        old_value = getattr(old_instance, field, None)
        new_value = getattr(new_instance, field, None)

        if old_value != new_value:
            changes[field] = {
                'old': str(old_value),
                'new': str(new_value)
            }

    return changes


class AuditLogDecorator:
    def __init__(self, action, description_template):
        self.action = action
        self.description_template = description_template

    def __call__(self, func):
        def wrapper(request, *args, **kwargs):
            from .models import AuditLog
            import time

            start_time = time.time()
            error = None
            result = None

            try:
                result = func(request, *args, **kwargs)
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                duration = int((time.time() - start_time) * 1000)

                # Create audit log
                try:
                    description = self.description_template.format(
                        **kwargs,
                        user=request.user.get_full_name() if request.user.is_authenticated else 'Anonymous'
                    )
                except:
                    description = self.description_template

                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    action=self.action,
                    action_description=description,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    request_path=request.path,
                    request_method=request.method,
                    duration_ms=duration,
                    success=error is None,
                    error_message=error or '',
                    company=getattr(request.user, 'company', None) if request.user.is_authenticated else None
                )

        return wrapper



class audit_context:

    def __init__(self, request, action, description):
        self.request = request
        self.action = action
        self.description = description
        self.metadata = {}
        self.start_time = None
        self.audit_log = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        from .models import AuditLog

        duration = int((time.time() - self.start_time) * 1000)
        success = exc_type is None
        error_message = str(exc_val) if exc_val else ''

        self.audit_log = AuditLog.objects.create(
            user=self.request.user if self.request.user.is_authenticated else None,
            action=self.action,
            action_description=self.description,
            ip_address=get_client_ip(self.request),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
            request_path=self.request.path,
            request_method=self.request.method,
            duration_ms=duration,
            success=success,
            error_message=error_message,
            metadata=self.metadata,
            company=getattr(self.request.user, 'company', None) if self.request.user.is_authenticated else None
        )

        return False  # Don't suppress exceptions

    def add_metadata(self, key, value):
        """Add metadata to the audit log"""
        self.metadata[key] = value



def export_audit_logs(queryset, format='csv'):
    import csv
    import io
    from django.utils import timezone

    if format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'Timestamp', 'User', 'Action', 'Description',
            'Resource', 'IP Address', 'Success', 'Duration (ms)'
        ])

        # Write data
        for log in queryset:
            writer.writerow([
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.user.get_full_name() if log.user else 'System',
                log.get_action_display(),
                log.action_description,
                log.resource_name,
                log.ip_address,
                'Yes' if log.success else 'No',
                log.duration_ms or ''
            ])

        return output.getvalue()

    elif format == 'excel':
        # Implement Excel export using openpyxl or xlsxwriter
        pass

    return None