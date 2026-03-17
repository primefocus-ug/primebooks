from django.contrib.auth import get_user_model
from django_tenants.utils import get_tenant_model, schema_context
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)
User = get_user_model()
Company = get_tenant_model()


# ---------------------------------------------------------------------------
# find_user_tenants_by_email   (replaces the old single-match version)
#
# The old find_user_tenant_by_email() stopped at the first tenant it found,
# and because the queryset was ordered by -created_at, it always returned
# the most-recently-created tenant — wrong for any user who belongs to more
# than one company.
#
# The new function returns a LIST of (schema_name, tenant) tuples so the
# caller can either proceed directly (single match) or show a company-picker
# (multiple matches).
#
# The old name is kept as a backwards-compatible shim that returns the first
# element of the list, preserving behaviour for any callers that only ever
# deal with single-tenant users.
# ---------------------------------------------------------------------------

def find_user_tenants_by_email(email):
    """
    Search every active tenant for a user with the given email.

    Returns a list of (schema_name, tenant) tuples — one entry per tenant
    where the email exists and the tenant has active access.  Empty list if
    not found anywhere.
    """
    email = email.lower().strip()
    matches = []

    # Per-email cache stores a list of schema names now, not a single value.
    cache_key = f'user_tenant_email_{email}'
    cached_schemas = cache.get(cache_key)

    if cached_schemas:
        # Validate every cached schema is still live
        valid = []
        for schema_name in cached_schemas:
            try:
                tenant = Company.objects.get(schema_name=schema_name)
                if tenant.has_active_access:
                    valid.append((schema_name, tenant))
            except Company.DoesNotExist:
                pass  # tenant removed — skip

        if valid:
            logger.info(f"Cache hit: {email} found in {[s for s,_ in valid]}")
            return valid

        # All cached entries gone — fall through to full scan
        cache.delete(cache_key)

    # Full scan — stable order (pk) so results are deterministic
    active_tenants = Company.objects.filter(
        is_active=True,
        status__in=['ACTIVE', 'TRIAL']
    ).order_by('pk')

    for tenant in active_tenants:
        try:
            with schema_context(tenant.schema_name):
                user_exists = User.objects.filter(
                    email=email,
                    is_active=True
                ).exists()

                if user_exists and tenant.has_active_access:
                    matches.append((tenant.schema_name, tenant))
                    logger.info(f"Found {email} in tenant {tenant.schema_name}")

        except Exception as e:
            logger.error(f"Error searching tenant {tenant.schema_name}: {e}")
            continue

    if matches:
        # Cache the list of matching schema names for 1 hour
        cache.set(cache_key, [s for s, _ in matches], 3600)
    else:
        logger.warning(f"User {email} not found in any active tenant")

    return matches


def find_user_tenant_by_email(email):
    """
    Backwards-compatible shim.

    Returns (schema_name, tenant) for the single match, or (None, None).
    If the user belongs to more than one tenant this returns the first one
    found — callers that need multi-tenant support should use
    find_user_tenants_by_email() directly.
    """
    matches = find_user_tenants_by_email(email)
    if matches:
        return matches[0]
    return None, None


def verify_user_credentials(email, password, tenant_schema):
    email = email.lower().strip()

    try:
        with schema_context(tenant_schema):
            user = User.objects.filter(email=email, is_active=True).first()

            if user and user.check_password(password):
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


def get_tenant_login_url(tenant_schema, token=None, next_url=None):
    from django.conf import settings
    from urllib.parse import urlencode

    try:
        tenant = Company.objects.get(schema_name=tenant_schema)

        protocol = 'https' if getattr(settings, 'USE_HTTPS', False) else 'http'
        base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost:8000')

        if ':' in base_domain:
            host, port = base_domain.rsplit(':', 1)
        else:
            host = base_domain
            port = '8000'

        domain = f"{tenant_schema}.{host}:{port}"
        url = f"{protocol}://{domain}/accounts/login/complete/"

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


# ---------------------------------------------------------------------------
# Token helpers — delegate to the canonical implementations in
# public_router/views.py which use cache key ``login_token:{token}``
# (colon, native dict).  The old standalone versions here used
# ``login_token_{token}`` (underscore, JSON string) causing every token
# to be unreadable by the accounts app.
# ---------------------------------------------------------------------------

def create_login_token(email, tenant_schema, expires_in=300):
    """
    Thin wrapper — delegates to public_router.views.create_login_token.
    ``expires_in`` is accepted for backwards-compat but not forwarded;
    the canonical TTL (LOGIN_TOKEN_EXPIRY = 300 s) is used instead.
    """
    from public_router.views import create_login_token as _canonical_create
    return _canonical_create(email, tenant_schema, user_id=None)


def verify_login_token(token):
    """
    Verify and consume a login token.
    Returns (email, tenant_schema) or (None, None).
    Delegates to public_router.views.validate_and_consume_token.
    """
    from public_router.views import validate_and_consume_token

    token_data = validate_and_consume_token(token)

    if not token_data:
        logger.warning("Invalid or expired login token")
        return None, None

    email = token_data.get('email')
    tenant_schema = token_data.get('tenant_schema')

    if not email or not tenant_schema:
        logger.error(f"Token data missing required fields: {list(token_data.keys())}")
        return None, None

    logger.info(f"Verified login token for {email}")
    return email, tenant_schema