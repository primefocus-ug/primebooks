from django.contrib.auth import get_user_model
from django_tenants.utils import get_tenant_model, schema_context
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)
User = get_user_model()
Company = get_tenant_model()


def find_user_tenant_by_email(email):
    email = email.lower().strip()

    # Check cache first
    cache_key = f'user_tenant_email_{email}'
    cached_schema = cache.get(cache_key)

    if cached_schema:
        try:
            tenant = Company.objects.get(schema_name=cached_schema)
            if tenant.has_active_access:
                return cached_schema, tenant
        except Company.DoesNotExist:
            cache.delete(cache_key)

    # Search across all active tenants
    active_tenants = Company.objects.filter(
        is_active=True,
        status__in=['ACTIVE', 'TRIAL']
    ).order_by('-created_at')  # Newer tenants first

    for tenant in active_tenants:
        try:
            with schema_context(tenant.schema_name):
                user_exists = User.objects.filter(
                    email=email,
                    is_active=True
                ).exists()

                if user_exists:
                    # Verify company has active access
                    if tenant.has_active_access:
                        # Cache for 1 hour
                        cache.set(cache_key, tenant.schema_name, 3600)
                        logger.info(f"Found user {email} in tenant {tenant.schema_name}")
                        return tenant.schema_name, tenant

        except Exception as e:
            logger.error(f"Error searching tenant {tenant.schema_name}: {e}")
            continue

    logger.warning(f"User {email} not found in any active tenant")
    return None, None


def verify_user_credentials(email, password, tenant_schema):
    email = email.lower().strip()

    try:
        with schema_context(tenant_schema):
            user = User.objects.filter(email=email, is_active=True).first()

            if user and user.check_password(password):
                # Check company access
                if hasattr(user, 'company') and user.company.has_active_access:
                    logger.info(f"Credentials verified for {email} in {tenant_schema}")
                    return user
                else:
                    logger.warning(f"User {email} company has no active access")
            else:
                logger.warning(f"Invalid password for {email} in {tenant_schema}")

    except Exception as e:
        logger.error(f"Error verifying credentials in {tenant_schema}: {e}")

    return None


# public_router/tenant_lookup.py

def get_tenant_login_url(tenant_schema, token=None, next_url=None):
    from django.conf import settings
    from urllib.parse import urlencode

    try:
        tenant = Company.objects.get(schema_name=tenant_schema)

        # Protocol
        protocol = 'https' if getattr(settings, 'USE_HTTPS', False) else 'http'

        # Get base domain with port
        base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost:8000')

        # Parse base domain to extract host and port
        if ':' in base_domain:
            host, port = base_domain.rsplit(':', 1)
        else:
            host = base_domain
            port = '8000'  # Default port for development

        # Build full domain with subdomain and port
        domain = f"{tenant_schema}.{host}:{port}"

        # Build URL
        url = f"{protocol}://{domain}/accounts/login/complete/"

        # Add parameters
        params = {}
        if token:
            params['token'] = token
        if next_url:
            params['next'] = next_url

        if params:
            url += f"?{urlencode(params)}"

        logger.info(f"Generated tenant login URL: {url}")
        return url

    except Company.DoesNotExist:
        logger.error(f"Tenant {tenant_schema} not found")
        return None
    except Exception as e:
        logger.error(f"Error generating tenant login URL: {e}")
        return None


def create_login_token(email, tenant_schema, expires_in=300):
    import secrets
    import json
    from datetime import datetime, timedelta

    token = secrets.token_urlsafe(32)

    token_data = {
        'email': email,
        'tenant_schema': tenant_schema,
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(seconds=expires_in)).isoformat()
    }

    cache_key = f'login_token_{token}'
    cache.set(cache_key, json.dumps(token_data), expires_in)

    logger.info(f"Created login token for {email} in {tenant_schema}")
    return token


def verify_login_token(token):
    """
    Verify and consume login token

    Returns: (email, tenant_schema) or (None, None)
    """
    import json
    from datetime import datetime

    cache_key = f'login_token_{token}'
    token_data_str = cache.get(cache_key)

    if not token_data_str:
        logger.warning("Invalid or expired login token")
        return None, None

    try:
        token_data = json.loads(token_data_str)

        # Check expiration
        expires_at = datetime.fromisoformat(token_data['expires_at'])
        if datetime.now() > expires_at:
            cache.delete(cache_key)
            logger.warning("Expired login token")
            return None, None

        email = token_data['email']
        tenant_schema = token_data['tenant_schema']

        # Consume token (one-time use)
        cache.delete(cache_key)

        logger.info(f"Verified login token for {email}")
        return email, tenant_schema

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error verifying login token: {e}")
        cache.delete(cache_key)
        return None, None

