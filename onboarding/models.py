"""
onboarding/models.py

Tracks per-user onboarding progress.
One OnboardingProgress row per user, updated as steps are completed.

Steps:
  company_profile  — Company profile completed
  first_product    — First product/service added
  invite_user      — First team member invited
  first_invoice    — First invoice or sale created
  efris_config     — EFRIS configured (optional)

Add to settings.py:
  INSTALLED_APPS += ['onboarding']

Add to main urls.py:
  path('onboarding/', include('onboarding.urls')),

Add context processor to TEMPLATES[0]['OPTIONS']['context_processors']:
  'onboarding.context_processors.onboarding_context',
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


# ── Step definitions (single source of truth) ────────────────────────────────

ONBOARDING_STEPS = [
    {
        'key':         'company_profile',
        'label':       'Complete your company profile',
        'description': 'Fill in your company name, address, and contact details.',
        'url':         '/settings/company/',
        'icon':        'bi-building',
        'required':    True,
        'order':       1,
    },
    {
        'key':         'first_product',
        'label':       'Add your first product or service',
        'description': 'Add at least one product or service to your inventory.',
        'url':         '/products/create/',
        'icon':        'bi-box-seam',
        'required':    True,
        'order':       2,
    },
    {
        'key':         'invite_user',
        'label':       'Invite a team member',
        'description': 'Invite a colleague to join your PrimeBooks workspace.',
        'url':         '/users/create/',
        'icon':        'bi-person-plus',
        'required':    False,
        'order':       3,
    },
    {
        'key':         'first_invoice',
        'label':       'Create your first invoice or sale',
        'description': 'Create an invoice or record a sale to a customer.',
        'url':         '/invoices/create/',
        'icon':        'bi-receipt',
        'required':    True,
        'order':       4,
    },
    {
        'key':         'efris_config',
        'label':       'Configure EFRIS',
        'description': 'Set up your EFRIS credentials for tax compliance.',
        'url':         '/settings/efris/',
        'icon':        'bi-shield-check',
        'required':    False,
        'order':       5,
    },
]

REQUIRED_STEPS = [s['key'] for s in ONBOARDING_STEPS if s['required']]
ALL_STEP_KEYS  = [s['key'] for s in ONBOARDING_STEPS]


class OnboardingProgress(models.Model):
    """One record per user tracking each onboarding step."""

    user              = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='onboarding_progress',
    )

    # Step completion booleans
    company_profile   = models.BooleanField(default=False)
    first_product     = models.BooleanField(default=False)
    invite_user       = models.BooleanField(default=False)
    first_invoice     = models.BooleanField(default=False)
    efris_config      = models.BooleanField(default=False)

    # Timestamps
    started_at        = models.DateTimeField(auto_now_add=True)
    completed_at      = models.DateTimeField(null=True, blank=True)

    # User preferences
    dismissed         = models.BooleanField(
        default=False,
        help_text='User permanently dismissed onboarding.',
    )
    welcome_seen      = models.BooleanField(
        default=False,
        help_text='Welcome modal has been shown.',
    )

    class Meta:
        verbose_name        = 'Onboarding Progress'
        verbose_name_plural = 'Onboarding Progress'

    def __str__(self):
        return f'{self.user} — {self.percent}% complete'

    # ── Properties ──────────────────────────────────────────────

    @property
    def completed_steps(self):
        """List of step keys the user has completed."""
        return [key for key in ALL_STEP_KEYS if getattr(self, key, False)]

    @property
    def percent(self):
        """Overall completion percentage across all steps."""
        total = len(ALL_STEP_KEYS)
        done  = len(self.completed_steps)
        return int((done / total) * 100) if total else 0

    @property
    def required_percent(self):
        """Completion percentage across required steps only."""
        done = sum(1 for key in REQUIRED_STEPS if getattr(self, key, False))
        return int((done / len(REQUIRED_STEPS)) * 100) if REQUIRED_STEPS else 0

    @property
    def is_complete(self):
        """True when all required steps are done."""
        return all(getattr(self, key, False) for key in REQUIRED_STEPS)

    @property
    def is_new_user(self):
        """
        True if the welcome modal has not been shown yet.
        Used in template context to decide whether to show onboarding.
        """
        return not self.welcome_seen and not self.dismissed

    def get_steps_with_status(self):
        """Return ONBOARDING_STEPS with a 'done' boolean merged in."""
        return [
            {**step, 'done': getattr(self, step['key'], False)}
            for step in ONBOARDING_STEPS
        ]

    # ── Mutators ────────────────────────────────────────────────

    def complete_step(self, step_key: str) -> bool:
        """
        Mark step as complete. Returns True if this was a new completion.
        Marks completed_at if all required steps are now done.
        Does NOT call save() — caller must save or use update_fields.
        """
        if step_key not in ALL_STEP_KEYS:
            return False
        if getattr(self, step_key, False):
            return False  # already done

        setattr(self, step_key, True)

        if self.is_complete and not self.completed_at:
            self.completed_at = timezone.now()

        return True

    def complete_step_and_save(self, step_key: str) -> bool:
        """Mark step complete and immediately save."""
        changed = self.complete_step(step_key)
        if changed:
            update_fields = [step_key]
            if self.completed_at:
                update_fields.append('completed_at')
            self.save(update_fields=update_fields)
        return changed

    # ── Class helpers ────────────────────────────────────────────

    @classmethod
    def get_or_create_for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj

    @classmethod
    def auto_detect_completed_steps(cls, user) -> 'OnboardingProgress':
        """
        Inspect the database to automatically mark steps that are already done.
        Safe to call frequently — uses get_or_create and only writes on change.

        IMPORTANT: Adjust the app_label strings below to match your project's
        actual app names (e.g. 'inventory' → 'products', 'sales' → 'invoices').
        """
        from django.apps import apps

        progress = cls.get_or_create_for_user(user)

        if progress.dismissed or progress.is_complete:
            return progress

        fields_to_save = []

        # company_profile
        if not progress.company_profile:
            try:
                Company = apps.get_model('accounts', 'Company')
                company = (
                    Company.objects.filter(users=user).first()
                    or getattr(user, 'company', None)
                )
                if company and company.name and getattr(company, 'address', None):
                    progress.company_profile = True
                    fields_to_save.append('company_profile')
            except LookupError:
                pass

        # first_product
        if not progress.first_product:
            try:
                Product = apps.get_model('inventory', 'Product')
                if Product.objects.filter(
                    created_by=user
                ).exists() or Product.objects.exists():
                    progress.first_product = True
                    fields_to_save.append('first_product')
            except LookupError:
                pass

        # invite_user
        if not progress.invite_user:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                if User.objects.exclude(pk=user.pk).filter(is_active=True).exists():
                    progress.invite_user = True
                    fields_to_save.append('invite_user')
            except Exception:
                pass

        # first_invoice
        if not progress.first_invoice:
            try:
                Invoice = apps.get_model('sales', 'Invoice')
                if Invoice.objects.filter(created_by=user).exists():
                    progress.first_invoice = True
                    fields_to_save.append('first_invoice')
            except LookupError:
                pass

        # efris_config
        if not progress.efris_config:
            try:
                EfrisConfig = apps.get_model('efris', 'EfrisConfig')
                if EfrisConfig.objects.filter(is_active=True).exists():
                    progress.efris_config = True
                    fields_to_save.append('efris_config')
            except LookupError:
                pass

        if fields_to_save:
            if progress.is_complete and not progress.completed_at:
                progress.completed_at = timezone.now()
                fields_to_save.append('completed_at')
            progress.save(update_fields=fields_to_save)

        return progress