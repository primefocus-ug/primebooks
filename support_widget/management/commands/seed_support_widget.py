"""
support_widget/management/commands/seed_support_widget.py

Seeds initial FAQ entries and widget config for every tenant schema.

Usage:
    python manage.py seed_support_widget
    python manage.py seed_support_widget --schema=acme    # single tenant
    python manage.py seed_support_widget --overwrite      # re-seed even if FAQs exist
"""

from django.core.management.base import BaseCommand
from django_tenants.utils        import schema_context, get_tenant_model


SAMPLE_FAQS = [
    {
        'question':   'How do I reset my password?',
        'answer':     'Go to Settings → Account → Change Password. If you are locked out, click "Forgot Password" on the login page and follow the email instructions.',
        'keywords':   'password, reset, forgot, login, locked',
        'sort_order': 1,
    },
    {
        'question':   'How do I add a new product or service?',
        'answer':     'Navigate to Inventory → Products and click "Add Product". Fill in the name, SKU, price, and tax category, then save.',
        'keywords':   'product, service, inventory, add, create, new item',
        'sort_order': 2,
    },
    {
        'question':   'How do I create an invoice?',
        'answer':     'Go to Sales → Invoices → New Invoice. Select the customer, add line items, set the payment terms, and click "Save & Send".',
        'keywords':   'invoice, billing, customer, sale, receipt',
        'sort_order': 3,
    },
    {
        'question':   'How do I configure EFRIS for tax compliance?',
        'answer':     'Go to Settings → EFRIS Configuration. Enter your TIN, device serial number, and EFRIS credentials from URA. Click "Test Connection" to verify before saving.',
        'keywords':   'efris, tax, ura, compliance, tin, fiscal',
        'sort_order': 4,
    },
    {
        'question':   'How do I invite team members?',
        'answer':     'Go to Settings → Users → Invite User. Enter their email, select a role (Admin, Cashier, Accountant, etc.) and click Send Invitation.',
        'keywords':   'invite, user, team, staff, member, role',
        'sort_order': 5,
    },
    {
        'question':   'How do I export my sales report?',
        'answer':     'Go to Reports, select the report type and date range, then click the Download button to export as PDF or Excel.',
        'keywords':   'report, export, download, sales, pdf, excel',
        'sort_order': 6,
    },
    {
        'question':   'Can I use PrimeBooks offline?',
        'answer':     'Yes — the desktop app works fully offline. Changes sync automatically when you reconnect to the internet.',
        'keywords':   'offline, desktop, sync, internet, connection',
        'sort_order': 7,
    },
    {
        'question':   'How do I set up multiple branches or stores?',
        'answer':     'Go to Settings → Branches and click "Add Branch". Each branch can have its own inventory, cashiers, and reports.',
        'keywords':   'branch, store, location, multiple, outlet',
        'sort_order': 8,
    },
]

DEFAULT_CONFIG = {
    'greeting_message':      "👋 Hi there! Welcome to PrimeBooks Support. How can we help you today?",
    'widget_title':          "PrimeBooks Support",
    'brand_color':           "#6366f1",
    'call_recording_notice': (
        "⚠️ This call is recorded for quality and training purposes. "
        "By continuing, you consent to the recording of this call."
    ),
    'business_hours_message': (
        "Our support agents are currently offline. "
        "Leave a message and we'll get back to you by email shortly."
    ),
    'is_active': True,
}


class Command(BaseCommand):
    help = "Seed support widget config and FAQ entries for all (or one) tenant(s)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema', type=str, default=None,
            help="Only seed a specific tenant schema (e.g. --schema=acme)",
        )
        parser.add_argument(
            '--overwrite', action='store_true', default=False,
            help="Re-create FAQs even if they already exist",
        )

    def handle(self, *args, **options):
        target_schema = options['schema']
        overwrite     = options['overwrite']

        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.exclude(schema_name='public')
        if target_schema:
            tenants = tenants.filter(schema_name=target_schema)
            if not tenants.exists():
                self.stderr.write(f"Schema '{target_schema}' not found.")
                return

        for tenant in tenants:
            self._seed_tenant(tenant.schema_name, overwrite)

    def _seed_tenant(self, schema_name, overwrite):
        from support_widget.models import SupportWidgetConfig, FAQ

        with schema_context(schema_name):
            # ── Config ─────────────────────────────────────────────────────
            config, created = SupportWidgetConfig.objects.get_or_create(pk=1)
            if created or overwrite:
                for k, v in DEFAULT_CONFIG.items():
                    setattr(config, k, v)
                config.save()
                self.stdout.write(
                    self.style.SUCCESS(f"  [{schema_name}] ✅ Widget config {'created' if created else 'updated'}")
                )
            else:
                self.stdout.write(f"  [{schema_name}] — Widget config already exists, skipping")

            # ── FAQs ────────────────────────────────────────────────────────
            existing = FAQ.objects.count()
            if existing and not overwrite:
                self.stdout.write(
                    f"  [{schema_name}] — {existing} FAQ(s) already exist, skipping (use --overwrite to force)"
                )
                return

            if overwrite:
                FAQ.objects.all().delete()
                self.stdout.write(f"  [{schema_name}] — Deleted existing FAQs")

            for faq_data in SAMPLE_FAQS:
                FAQ.objects.create(**faq_data)

            self.stdout.write(
                self.style.SUCCESS(f"  [{schema_name}] ✅ Created {len(SAMPLE_FAQS)} FAQ entries")
            )