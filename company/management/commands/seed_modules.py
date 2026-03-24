# company/management/commands/seed_modules.py

from django.core.management.base import BaseCommand
from company.models import AvailableModule


class Command(BaseCommand):
    help = 'Seed the AvailableModule catalog with your business modules'

    def handle(self, *args, **kwargs):
        modules = [
            dict(key='sales',       label='Sales',             icon='bi bi-cart-check',            monthly_price=15000, display_order=1),
            dict(key='inventory',   label='Inventory',         icon='bi bi-boxes',                 monthly_price=15000, display_order=2),
            dict(key='expenses',    label='Finance & Expenses',icon='bi bi-cash-stack',            monthly_price=10000, display_order=3),
            dict(key='invoices',    label='Invoices',          icon='bi bi-receipt',               monthly_price=10000, display_order=4),
            dict(key='customers',   label='Customers',         icon='bi bi-people-fill',           monthly_price=8000,  display_order=5),
            dict(key='reports',     label='Reports',           icon='bi bi-file-earmark-bar-graph',monthly_price=10000, display_order=6),
            dict(key='efris',       label='EFRIS Integration', icon='bi bi-receipt-cutoff',        monthly_price=20000, display_order=7),
            dict(key='messaging',   label='Messaging',         icon='bi bi-chat-dots',             monthly_price=5000,  display_order=9),
        ]

        for m in modules:
            obj, created = AvailableModule.objects.get_or_create(
                key=m['key'],
                defaults={
                    'label':                 m['label'],
                    'description':           f"{m['label']} module for PrimeBooks.",
                    'icon':                  m['icon'],
                    'monthly_price':         m['monthly_price'],
                    'display_order':         m['display_order'],
                    'is_publicly_available': True,
                }
            )
            status = '✅ Created' if created else '↩️  Already exists'
            self.stdout.write(f"  {status}: {m['label']}")

        self.stdout.write(self.style.SUCCESS('\nModule catalog seeded.'))