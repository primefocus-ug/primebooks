from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from functools import wraps

User = get_user_model()


def get_visible_users(queryset=None, company=None):
    """
    Get only visible users (excluding hidden SaaS admins)

    Args:
        queryset: Optional base queryset to filter
        company: Optional company to filter by

    Returns:
        QuerySet of visible users
    """
    if queryset is None:
        queryset = User.objects.all()

    # Filter out hidden users
    queryset = queryset.filter(is_hidden=False)

    # Filter by company if specified
    if company:
        queryset = queryset.filter(company=company)

    return queryset


def get_company_user_count(company, active_only=True):
    """
    Get user count for a company excluding hidden users

    Args:
        company: Company instance
        active_only: Whether to count only active users

    Returns:
        int: Number of visible users
    """
    queryset = User.objects.filter(company=company, is_hidden=False)

    if active_only:
        queryset = queryset.filter(is_active=True)

    return queryset.count()


def get_accessible_companies(user):
    """
    Get companies accessible to a user

    Args:
        user: User instance

    Returns:
        QuerySet of companies the user can access
    """
    from company.models import Company

    if not user.is_authenticated:
        return Company.objects.none()

    if getattr(user, 'is_saas_admin', False) or getattr(user, 'can_access_all_companies', False):
        return Company.objects.all()

    if hasattr(user, 'company') and user.company:
        return Company.objects.filter(pk=user.company.pk)  # ✅ use pk, works with company_id

    return Company.objects.none()



def can_access_company(user, company):
    """
    Check if a user can access a specific company

    Args:
        user: User instance
        company: Company instance

    Returns:
        bool: True if user can access the company
    """
    if not user.is_authenticated:
        return False

    if getattr(user, 'is_saas_admin', False):
        return True

    if getattr(user, 'can_access_all_companies', False):
        return True

    if hasattr(user, 'company') and user.company:
        return user.company.id == company.id

    return False


def require_saas_admin(view_func):
    """
    Decorator to require SaaS admin permissions

    Usage:
        @require_saas_admin
        def my_view(request):
            # Only SaaS admins can access this view
            pass
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")

        if not getattr(request.user, 'is_saas_admin', False):
            raise PermissionDenied("SaaS admin permissions required")

        return view_func(request, *args, **kwargs)

    return wrapper


def require_company_access(company_param='company_id'):
    """
    Decorator to check if user can access a specific company

    Args:
        company_param: Name of the parameter containing company ID

    Usage:
        @require_company_access('company_id')
        def my_view(request, company_id):
            # User must have access to the company
            pass
    """

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
                company = Company.objects.get(id=company_id)
            except Company.DoesNotExist:
                raise PermissionDenied("Company not found")

            # Check access
            if not can_access_company(request.user, company):
                raise PermissionDenied("You don't have access to this company")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def create_company_default_admin(company, admin_email=None, admin_password=None):
    """
    Create a default admin user for a new company

    Args:
        company: Company instance
        admin_email: Optional email for the admin
        admin_password: Optional password for the admin

    Returns:
        User instance of the created admin
    """
    if not admin_email:
        admin_email = f"admin@{company.schema_name}.com"

    if not admin_password:
        import secrets
        admin_password = secrets.token_urlsafe(12)

    # Check if admin already exists
    existing_admin = User.objects.filter(
        company=company,
        user_type='COMPANY_ADMIN'
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
        user_type='COMPANY_ADMIN',
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

