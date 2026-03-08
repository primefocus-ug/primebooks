from celery import shared_task
from django.db import transaction, connection
from django.utils import timezone
from django_tenants.utils import schema_context
from datetime import timedelta
import logging
import time
import secrets
from celery.exceptions import SoftTimeLimitExceeded

from .models import TenantSignupRequest
from company.models import Company, Domain, SubscriptionPlan
from accounts.models import CustomUser

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────────────────────────────────────

def _close_old_connections():
    """
    Discard stale DB connections before any ORM work in a Celery task.

    Workers sit idle between tasks; PostgreSQL silently drops connections
    that have been idle past tcp_keepalives_idle.  close_old_connections()
    forces Django to open a fresh socket on the next query instead of
    raising OperationalError: SSL connection has been closed unexpectedly.
    """
    from django.db import close_old_connections
    close_old_connections()


# ─────────────────────────────────────────────────────────────────────────────
# Main provisioning task
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=240,
    time_limit=300,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def create_tenant_async(self, signup_request_id, password):
    """
    Async Celery task: provisions a complete new tenant.

    Steps (all run in the worker, never in the HTTP cycle):
      1. Lock + mark PROCESSING
      2. Create Company + Domain rows  (under advisory lock)
      3. Poll until django-tenants finishes running migrations
      4. Create the main Store inside the tenant schema
      5. Create admin user with their signup password + Company Admin role
      6. Mark COMPLETED
      7. Send welcome email with one-time magic login link
    """
    _close_old_connections()

    try:
        start_time = timezone.now()
        logger.info(f"Starting tenant creation for request {signup_request_id}")

        # ── 1. Lock the signup request ───────────────────────────────────
        try:
            with transaction.atomic():
                signup_request = TenantSignupRequest.objects.select_for_update(
                    nowait=False
                ).get(request_id=signup_request_id)

                if signup_request.status == 'COMPLETED':
                    logger.info(
                        f"Request {signup_request_id} already completed, skipping."
                    )
                    return {
                        'success': True,
                        'company_id': signup_request.created_company_id,
                        'already_completed': True,
                    }

                signup_request.status = 'PROCESSING'
                signup_request.save(update_fields=['status', 'updated_at'])

        except TenantSignupRequest.DoesNotExist:
            logger.error(f"Signup request {signup_request_id} not found")
            return {'success': False, 'error': 'Request not found'}

        # Non-blocking metrics — a failure here must never abort provisioning
        try:
            from .monitoring import track_signup_metrics
            track_signup_metrics(signup_request)
        except Exception as metrics_error:
            logger.warning(f"Failed to track metrics: {metrics_error}")

        # ── 2-5. Full tenant provisioning ────────────────────────────────
        company = create_tenant_with_lock(signup_request, password)

        execution_time = (timezone.now() - start_time).total_seconds()

        # ── 6. Mark COMPLETED ────────────────────────────────────────────
        with transaction.atomic():
            signup_request.status = 'COMPLETED'
            signup_request.tenant_created = True
            signup_request.created_company_id = company.company_id
            signup_request.created_schema_name = company.schema_name
            signup_request.completed_at = timezone.now()
            signup_request.save(update_fields=[
                'status', 'tenant_created', 'created_company_id',
                'created_schema_name', 'completed_at', 'updated_at',
            ])

        logger.info(
            f"Tenant {company.company_id} provisioned in "
            f"{execution_time:.2f}s for request {signup_request_id}"
        )

        # ── 7. Welcome email ─────────────────────────────────────────────
        # Runs in a separate task so a mail-server failure cannot affect
        # the provisioning success status.
        send_welcome_email.delay(company.company_id, signup_request_id)

        return {
            'success': True,
            'company_id': company.company_id,
            'schema_name': company.schema_name,
            'execution_time': execution_time,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"Tenant creation soft-timeout for request {signup_request_id}")
        _safe_mark_failed(
            signup_request_id, 'Operation timed out. Will retry…', self.request.retries
        )
        raise self.retry(countdown=120)

    except Exception as e:
        logger.error(
            f"Failed to create tenant for request {signup_request_id}: {e}",
            exc_info=True,
            extra={
                'signup_request_id': signup_request_id,
                'retry_count': self.request.retries,
            },
        )
        _safe_mark_failed(signup_request_id, str(e)[:1000], self.request.retries)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        else:
            try:
                from .monitoring import alert_on_high_failure_rate
                alert_on_high_failure_rate()
            except Exception:
                pass
            raise


def _safe_mark_failed(signup_request_id, error_message, retry_count):
    """Best-effort FAILED status update with a fresh DB connection."""
    try:
        _close_old_connections()
        with transaction.atomic():
            signup_request = TenantSignupRequest.objects.select_for_update().get(
                request_id=signup_request_id
            )
            signup_request.status = 'FAILED'
            signup_request.error_message = error_message
            signup_request.retry_count = retry_count
            signup_request.save(update_fields=[
                'status', 'error_message', 'retry_count', 'updated_at'
            ])
    except Exception as save_error:
        logger.error(
            f"Failed to mark signup {signup_request_id} as FAILED: {save_error}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Provisioning pipeline
# ─────────────────────────────────────────────────────────────────────────────

def create_tenant_with_lock(signup_request, password):
    """
    Orchestrates the four provisioning phases:

      A. (advisory lock)  Create Company + Domain rows
      B. (no lock)        Poll until migrations finish
      C. (no lock)        Create main Store in tenant schema
      D. (no lock)        Create admin user with their password + role

    The advisory lock wraps ONLY phase A.  Phases B-D run without any open
    lock or transaction so no DB connection is held captive during the
    migration polling sleep loop.
    """
    from .signal_utils import suppress_signals

    schema_name = f"tenant_{signup_request.subdomain}"
    lock_id = hash(schema_name) % 2147483647

    # ── A. Company + Domain ───────────────────────────────────────────────
    with _advisory_lock(lock_id):
        if Company.objects.filter(schema_name=schema_name).exists():
            raise ValueError(f"Schema {schema_name} already exists")

        with suppress_signals():
            with transaction.atomic():
                company = create_company(signup_request, schema_name)
                create_domain(signup_request, company)

    # Lock released — other workers are free.

    # ── B. Wait for migrations ────────────────────────────────────────────
    wait_for_schema_ready(company.schema_name)

    # ── C. Main Store ─────────────────────────────────────────────────────
    with suppress_signals():
        create_main_store(signup_request, company)

    # ── D. Admin user ─────────────────────────────────────────────────────
    with suppress_signals():
        create_admin_user(signup_request, company, password)

    logger.info(f"Full provisioning complete for schema {schema_name}")
    return company


# ─────────────────────────────────────────────────────────────────────────────
# Advisory lock context manager
# ─────────────────────────────────────────────────────────────────────────────

class _advisory_lock:
    """
    PostgreSQL session-level advisory lock as a context manager.

    pg_advisory_lock is session-scoped, NOT transaction-scoped — the lock
    persists until pg_advisory_unlock() is called or the session closes.
    __exit__ always unlocks, even when an exception is in flight.
    """

    def __init__(self, lock_id: int):
        self.lock_id = lock_id
        self.cursor = None

    def __enter__(self):
        self.cursor = connection.cursor()
        self.cursor.execute("SELECT pg_advisory_lock(%s)", [self.lock_id])
        logger.debug(f"Acquired advisory lock {self.lock_id}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.cursor:
                self.cursor.execute("SELECT pg_advisory_unlock(%s)", [self.lock_id])
                logger.debug(f"Released advisory lock {self.lock_id}")
        except Exception as unlock_err:
            logger.error(
                f"Failed to release advisory lock {self.lock_id}: {unlock_err}"
            )
        finally:
            if self.cursor:
                try:
                    self.cursor.close()
                except Exception:
                    pass
        return False  # Never suppress exceptions


# ─────────────────────────────────────────────────────────────────────────────
# Schema readiness poller
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_schema_ready(schema_name, max_retries=10, delay=2):
    """
    Poll until django-tenants has finished running migrations for the schema.

    Runs outside any open transaction and outside the advisory lock.
    Closes the connection before sleeping so no socket is held open during
    idle time.
    """
    for attempt in range(max_retries):
        try:
            with schema_context(schema_name):
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = %s
                            AND table_name = 'accounts_customuser'
                        )
                        """,
                        [schema_name],
                    )
                    table_exists = cursor.fetchone()[0]

                if table_exists:
                    logger.info(
                        f"Schema {schema_name} is ready (attempt {attempt + 1})"
                    )
                    return True

            logger.warning(
                f"Schema {schema_name} not ready, retry {attempt + 1}/{max_retries}"
            )
            connection.close()
            time.sleep(delay)

        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Error checking schema ({e}), retry {attempt + 1}/{max_retries}"
                )
                connection.close()
                time.sleep(delay)
            else:
                logger.error(f"Schema {schema_name} never became ready: {e}")
                raise

    raise TimeoutError(
        f"Schema {schema_name} did not become ready after {max_retries} attempts"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provisioning step functions
# ─────────────────────────────────────────────────────────────────────────────

def create_company(signup_request, schema_name):
    """Create the Company (tenant) row in the public schema."""

    plan = SubscriptionPlan.objects.filter(
        name=signup_request.selected_plan, is_active=True
    ).first()
    if not plan:
        logger.warning(
            f"Plan '{signup_request.selected_plan}' not found; falling back to FREE"
        )
        plan = SubscriptionPlan.objects.filter(name='FREE', is_active=True).first()
    if not plan:
        raise ValueError(
            f"No subscription plan found for '{signup_request.selected_plan}' "
            "and no FREE fallback exists. Cannot create company."
        )

    company = Company.objects.create(
        schema_name=schema_name,
        name=signup_request.company_name,
        trading_name=signup_request.trading_name or signup_request.company_name,
        email=signup_request.email,
        phone=signup_request.phone,
        plan=plan,
        is_trial=True,
        trial_ends_at=timezone.now().date() + timedelta(days=plan.trial_days),
        status='TRIAL',
    )

    logger.info(f"Created company: {company.company_id} ({schema_name})")
    return company


def create_domain(signup_request, company):
    """Create the primary Domain row for the tenant."""
    from django.conf import settings

    base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
    domain_name = f"{signup_request.subdomain}.{base_domain}"

    if Domain.objects.filter(domain=domain_name).exists():
        raise ValueError(f"Domain {domain_name} already exists")

    domain = Domain.objects.create(
        tenant=company,
        domain=domain_name,
        is_primary=True,
        ssl_enabled=getattr(settings, 'USE_SSL', True),
    )

    logger.info(f"Created domain: {domain.domain}")
    return domain


def create_main_store(signup_request, company):
    """
    Create the first Store for the tenant, seeded from signup details.

    - store_type='MAIN', is_main_branch=True  →  shows as HQ in the UI
    - accessible_by_all=True                  →  admin can restrict later
    - manager details seeded from the signup admin contact

    Idempotent: if a main store already exists (e.g. on task retry) the
    existing one is returned without creating a duplicate.
    """
    from stores.models import Store

    with schema_context(company.schema_name):
        existing = Store.objects.filter(
            company=company, is_main_branch=True
        ).first()
        if existing:
            logger.info(
                f"Main store already exists for {company.schema_name}, skipping."
            )
            return existing

        store = Store.objects.create(
            company=company,
            name=signup_request.trading_name or signup_request.company_name,
            store_type='MAIN',
            is_main_branch=True,
            accessible_by_all=True,
            phone=signup_request.phone or '',
            email=signup_request.email,
            location=signup_request.country or '',
            allows_sales=True,
            allows_inventory=True,
            is_active=True,
            manager_name=(
                f"{signup_request.first_name} {signup_request.last_name}".strip()
            ),
            manager_phone=signup_request.admin_phone or '',
        )

        logger.info(
            f"Created main store '{store.name}' (code={store.code}) "
            f"for schema {company.schema_name}"
        )
        return store


def create_admin_user(signup_request, company, password):
    """
    Create the Company Admin user inside the migrated tenant schema.

    Password handling
    ─────────────────
    `password` is the raw password the user typed during signup.
    CustomUser.objects.create_user() calls set_password() which runs it
    through Django's PASSWORD_HASHERS (PBKDF2 SHA-256 by default) and
    stores only the resulting hash.  The plaintext is never persisted.

    Role assignment
    ───────────────
    - company_admin=True  is the app-level flag for within-tenant admin rights
    - is_staff=False      Django admin is restricted to is_saas_admin only
                          (see CustomUser.has_module_perms)
    - _do_create_roles()  is called first so all system roles exist before
                          we try to assign one; it is fully idempotent
    - assign_role()       is used (not raw groups.add) so RoleHistory is logged
                          and capacity/active checks run

    Store assignment
    ────────────────
    The user is added to the main Store's staff + store_managers M2M sets
    so they can operate immediately after first login.
    """
    from django.contrib.auth.models import Group
    from accounts.models import Role
    from stores.models import Store

    with schema_context(company.schema_name):

        # ── Idempotency ──────────────────────────────────────────────────
        existing_user = CustomUser.objects.filter(
            email=signup_request.admin_email
        ).first()
        if existing_user:
            logger.info(f"Admin user already exists: {existing_user.email}")
            return existing_user

        # ── Create user ──────────────────────────────────────────────────
        # create_user() hashes `password` via set_password() — plaintext
        # is NEVER stored in the database.
        admin_user = CustomUser.objects.create_user(
            email=signup_request.admin_email,
            username=signup_request.admin_email.split('@')[0],
            password=password,          # user's own password, hashed internally
            first_name=signup_request.first_name,
            last_name=signup_request.last_name,
            phone_number=signup_request.admin_phone,
            company=company,
            company_admin=True,
            # is_staff is intentionally False.  CustomUser.has_module_perms()
            # restricts Django admin access to is_saas_admin only, so setting
            # is_staff=True on a company admin user has no effect and would
            # be misleading.  company_admin=True is the correct app-level flag.
            is_staff=False,
            is_active=True,
            email_verified=True,
        )

        # ── Seed all default roles ───────────────────────────────────────
        # create_tenant_with_lock wraps everything in suppress_signals(),
        # so the post_save(Company) → create_default_roles_for_tenant signal
        # was skipped.  We call _do_create_roles directly — it is fully
        # idempotent (get_or_create throughout) and safe to call on retries.
        try:
            from accounts.signals import _do_create_roles
            _do_create_roles(company)
            logger.info(f"Default roles seeded for schema {company.schema_name}")
        except Exception as roles_err:
            logger.warning(
                f"Could not seed default roles for {company.schema_name}: {roles_err}"
            )

        # ── Fetch the Company Admin Role ─────────────────────────────────
        # Role model facts (from accounts/models.py):
        #   • Role has NO 'name' field — name lives on role.group.name
        #   • Role.save() calls full_clean() which enforces:
        #       is_system_role=True  →  company MUST be None
        #   • unique_together = [['group', 'company']]
        #   • group is a OneToOneField, so each Group has exactly one Role
        #
        # _do_create_roles stores 'Company Admin' as:
        #   is_system_role=True, company=None  (see signals.py line 899-900)
        #
        # Therefore the correct lookup is group__name + company=None.
        # We use .get() (not get_or_create) because _do_create_roles above
        # already guarantees the Role exists; get_or_create would risk
        # creating a duplicate with wrong defaults if _do_create_roles failed.
        try:
            admin_role = Role.objects.get(
                group__name='Company Admin',
                company=None,       # system role — never tenant-specific
            )
        except Role.DoesNotExist:
            # _do_create_roles failed silently above; fall back to manual
            # creation with correct fields so provisioning is not blocked.
            logger.warning(
                "Company Admin role missing after seed attempt — "
                "creating it manually."
            )
            company_admin_group, _ = Group.objects.get_or_create(
                name='Company Admin'
            )
            admin_role, _ = Role.objects.get_or_create(
                group=company_admin_group,
                company=None,
                defaults={
                    'is_system_role': True,
                    'is_active': True,
                    'priority': 100,
                    'color_code': '#8b0000',
                    'description': (
                        'Tenant owner with full control over their company.'
                    ),
                },
            )

        # ── Assign role via the model method ─────────────────────────────
        # CustomUser.assign_role() does three things atomically:
        #   1. self.groups.add(role.group)   — grants all group permissions
        #   2. checks capacity / active flags
        #   3. creates a RoleHistory audit entry
        # We then set primary_role separately (assign_role doesn't do that).
        try:
            admin_user.assign_role(admin_role)
            logger.info(
                f"Assigned 'Company Admin' role to {admin_user.email} "
                f"via assign_role()"
            )
        except Exception as assign_err:
            # assign_role can raise ValidationError (capacity, inactive).
            # Fall back to direct group add so the user is never left roleless.
            logger.warning(
                f"assign_role() failed ({assign_err}); "
                f"falling back to direct groups.add()"
            )
            admin_user.groups.add(admin_role.group)

        admin_user.primary_role = admin_role
        admin_user.save(update_fields=['primary_role'])

        logger.info(
            f"primary_role set to '{admin_role.group.name}' "
            f"for {admin_user.email}"
        )

        # ── Assign to main store ─────────────────────────────────────────
        try:
            main_store = Store.objects.filter(
                company=company, is_main_branch=True
            ).first()
            if main_store:
                main_store.staff.add(admin_user)
                main_store.store_managers.add(admin_user)
                logger.info(
                    f"Assigned {admin_user.email} to store '{main_store.name}' "
                    f"as staff + manager"
                )
        except Exception as store_err:
            # Store assignment failure must never block user creation
            logger.warning(
                f"Could not assign admin to main store: {store_err}"
            )

        logger.info(f"Admin user ready: {admin_user.email}")
        return admin_user


# ─────────────────────────────────────────────────────────────────────────────
# Magic token + welcome email
# ─────────────────────────────────────────────────────────────────────────────

def _generate_magic_token(user_id, tenant_schema, email, ttl_seconds=3600):
    """
    Mint a one-time login token and store it in the cache.

    The token is consumed (deleted from cache) by the tenant-side
    complete_tenant_login view on first use, so it truly is one-time.
    Returns the raw token string.
    """
    from django.core.cache import cache

    # token_urlsafe(48) → 64 chars; validate_and_consume_token requires len >= 32
    token = secrets.token_urlsafe(48)
    cache.set(
        f"login_token:{token}",
        {
            'user_id': user_id,
            'tenant_schema': tenant_schema,
            'email': email,
            'created_at': timezone.now().isoformat(),
            # validate_and_consume_token (views.py) checks and sets this flag
            # to enforce single-use — MUST be present in the token payload
            'used': False,
        },
        timeout=ttl_seconds,
    )
    return token


@shared_task
def send_welcome_email(company_id, signup_request_id):
    """
    Send a welcome email containing:
      - The workspace login URL
      - The admin email address
      - A one-time magic login link (valid for 1 hour)

    Why no password in the email?
    The user set their password moments ago and already knows it.
    Sending it in plaintext email would be a security downgrade — anyone
    who can read the email (forwarded, leaked, etc.) would have the
    credentials.  The magic link provides frictionless first access; after
    it expires the user logs in with their email + password as normal.
    If they forget their password the standard reset flow handles it.
    """
    _close_old_connections()

    try:
        from django.core.mail import send_mail
        from django.conf import settings

        company = Company.objects.get(company_id=company_id)
        signup_request = TenantSignupRequest.objects.get(
            request_id=signup_request_id
        )

        base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
        default_lang = getattr(settings, 'LANGUAGE_CODE', 'en')

        # Protocol + port follows the same logic as get_tenant_login_url
        # in public_router/views.py: https in prod, http://host:8000 in DEBUG.
        protocol = 'https' if not settings.DEBUG else 'http'
        port_suffix = ':8000' if settings.DEBUG else ''
        tenant_base = (
            f"{protocol}://{signup_request.subdomain}.{base_domain}{port_suffix}"
        )

        # URL structure (from accounts/urls.py with i18n_patterns prefix):
        #   Login page:     /{lang}/accounts/login/
        #   Password reset: /{lang}/accounts/password-reset/
        #
        # Magic link complete_tenant_login view:
        #   /accounts/login/complete/?token=  (NO lang prefix — matches
        #   get_tenant_login_url() in public_router/views.py line 1029)
        login_url = f"{tenant_base}/{default_lang}/accounts/login/"
        password_reset_url = f"{tenant_base}/{default_lang}/accounts/password-reset/"

        # ── Generate magic link ──────────────────────────────────────────
        # The token payload MUST match what validate_and_consume_token()
        # in public_router/views.py expects:
        #   cache key:  login_token:{token}
        #   fields:     user_id, tenant_schema, email, created_at, used
        # TTL is 1 hour — token is single-use due to the 'used' flag.
        magic_link = None
        try:
            with schema_context(company.schema_name):
                user = CustomUser.objects.filter(
                    email=signup_request.admin_email
                ).first()

            if user:
                token = _generate_magic_token(
                    user_id=user.pk,
                    tenant_schema=company.schema_name,
                    email=signup_request.admin_email,
                    ttl_seconds=3600,
                )
                # Path matches get_tenant_login_url() exactly — no lang prefix
                magic_link = f"{tenant_base}/accounts/login/complete/?token={token}"
                logger.info(
                    f"Magic login token generated for {signup_request.admin_email}"
                )
        except Exception as token_err:
            # Token failure must NOT prevent the email from sending
            logger.warning(f"Could not generate magic link: {token_err}")

        # ── Compose email ────────────────────────────────────────────────
        subject = f"Your Primebooks workspace is ready — {company.name}"

        if magic_link:
            access_section = (
                f"Click the link below to access your workspace instantly\n"
                f"(valid for 1 hour, single use only):\n\n"
                f"  {magic_link}\n\n"
                f"After the link expires, log in normally at:\n"
                f"  {login_url}\n\n"
                f"Forgotten your password? Reset it here:\n"
                f"  {password_reset_url}\n"
            )
        else:
            access_section = (
                f"Log in at:\n"
                f"  {login_url}\n\n"
                f"Use the email and password you set during signup.\n"
                f"Forgotten your password? Reset it here:\n"
                f"  {password_reset_url}\n"
            )

        message = (
            f"Hi {signup_request.first_name},\n\n"
            f"Your Primebooks workspace is live and ready to use!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Workspace:   {company.name}\n"
            f"Login URL:   {login_url}\n"
            f"Your email:  {signup_request.admin_email}\n"
            f"Trial ends:  {company.trial_ends_at}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{access_section}\n"
            f"Need help getting started?\n"
            f"Reply to this email or WhatsApp us on +256 785 230 670.\n\n"
            f"Best regards,\n"
            f"The Primebooks Team\n"
        )

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [signup_request.admin_email],
            fail_silently=False,
        )

        logger.info(
            f"Welcome email dispatched to {signup_request.admin_email} "
            f"(magic_link={'included' if magic_link else 'omitted — token error'})"
        )

    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Periodic cleanup tasks (Celery Beat)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def cleanup_failed_signups():
    """
    Auto-retry FAILED signups that still have retries left.
    Celery Beat: every 5 minutes.
    """
    _close_old_connections()

    one_hour_ago = timezone.now() - timedelta(hours=1)

    failed_signups = TenantSignupRequest.objects.filter(
        status='FAILED',
        retry_count__lt=3,
        updated_at__gte=one_hour_ago,
    ).select_related('approval_workflow')

    for signup in failed_signups:
        try:
            workflow = getattr(signup, 'approval_workflow', None)
            password = workflow.generated_password if workflow else None

            if not password:
                logger.warning(
                    f"cleanup_failed_signups: no stored password for "
                    f"{signup.request_id} — use the admin Retry action."
                )
                continue

            logger.info(f"Auto-retrying failed signup: {signup.request_id}")
            create_tenant_async.apply_async(
                args=[str(signup.request_id), password],
                countdown=5,
            )

        except Exception as e:
            logger.error(
                f"cleanup_failed_signups: error queuing retry for "
                f"{signup.request_id}: {e}"
            )


@shared_task
def cleanup_stale_pending_signups():
    """
    Reset signups stuck in PENDING/PROCESSING for more than 10 minutes.
    Celery Beat: every 15 minutes.
    """
    _close_old_connections()

    ten_minutes_ago = timezone.now() - timedelta(minutes=10)

    stale_signups = TenantSignupRequest.objects.filter(
        status__in=['PENDING', 'PROCESSING'],
        created_at__lt=ten_minutes_ago,
    )

    for signup in stale_signups:
        logger.warning(
            f"Stale signup {signup.request_id} (status={signup.status}) → FAILED"
        )
        signup.status = 'FAILED'
        signup.error_message = (
            'Processing timeout — please retry via the admin panel '
            'or contact support.'
        )
        signup.save(update_fields=['status', 'error_message', 'updated_at'])