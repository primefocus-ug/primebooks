# company/management/commands/grandfather_modules.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from company.models import Company, AvailableModule, CompanyModule


class Command(BaseCommand):
    help = 'Grandfather existing tenants into core modules at no charge'

    GRANDFATHER_KEYS = [
        'sales', 'inventory', 'expenses', 'invoices',
        'customers', 'reports', 'messaging','efris'
    ]

    def handle(self, *args, **kwargs):
        companies = Company.objects.exclude(schema_name='public')

        if not companies.exists():
            self.stdout.write(self.style.WARNING('No tenant companies found.'))
            return

        # Pre-fetch modules once — fail fast if any are missing
        modules = {}
        missing = []
        for key in self.GRANDFATHER_KEYS:
            try:
                modules[key] = AvailableModule.objects.get(key=key)
            except AvailableModule.DoesNotExist:
                missing.append(key)

        if missing:
            self.stdout.write(self.style.ERROR(
                f"Missing modules (run seed_modules first): {', '.join(missing)}"
            ))
            return

        total_created = 0
        total_activated = 0

        for company in companies:
            created_count = 0
            activated_count = 0

            for key, module in modules.items():
                cm, created = CompanyModule.objects.get_or_create(
                    company=company,
                    module=module,
                    defaults={'is_active': True, 'activated_at': timezone.now()}
                )
                if created:
                    created_count += 1
                elif not cm.is_active:
                    cm.is_active = True
                    cm.activated_at = timezone.now()
                    cm.save()
                    activated_count += 1

            total_created += created_count
            total_activated += activated_count

            self.stdout.write(
                f"  ✅ {company.schema_name} — "
                f"{created_count} created, {activated_count} re-activated"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {companies.count()} tenants processed — "
            f"{total_created} modules created, {total_activated} re-activated."
        ))