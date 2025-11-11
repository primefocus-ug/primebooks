from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from company.models import Company
from inventory.models import Service
from efris.services import EFRISServiceManager


class Command(BaseCommand):
    help = 'Validate all services for EFRIS compliance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            help='Schema name of the tenant',
        )

        parser.add_argument(
            '--fix',
            action='store_true',
            help='Attempt to auto-fix common issues',
        )

    def handle(self, *args, **options):
        schema_name = options.get('schema')
        fix = options.get('fix')

        if schema_name:
            companies = [Company.objects.get(schema_name=schema_name)]
        else:
            companies = Company.objects.filter(is_active=True)

        for company in companies:
            self.stdout.write(
                self.style.SUCCESS(f'\n{"=" * 60}\n{company.name}\n{"=" * 60}')
            )

            with schema_context(company.schema_name):
                services = Service.objects.filter(
                    is_active=True,
                    efris_auto_sync_enabled=True
                )

                manager = EFRISServiceManager(company)

                total = services.count()
                compliant = 0
                non_compliant = 0

                for service in services:
                    is_valid, errors = manager.validate_service_for_efris(service)

                    if is_valid:
                        compliant += 1
                        self.stdout.write(f'  ✓ {service.name}')
                    else:
                        non_compliant += 1
                        self.stdout.write(
                            self.style.WARNING(f'  ⚠️  {service.name}:')
                        )
                        for error in errors:
                            self.stdout.write(f'     - {error}')

                        if fix:
                            self._attempt_fix(service, errors)

                self.stdout.write(f'\nTotal: {total}')
                self.stdout.write(self.style.SUCCESS(f'Compliant: {compliant}'))
                if non_compliant > 0:
                    self.stdout.write(
                        self.style.WARNING(f'Non-compliant: {non_compliant}')
                    )

    def _attempt_fix(self, service, errors):
        """Attempt to auto-fix common issues"""
        fixed = False

        for error in errors:
            if 'code is required' in error.lower():
                if not service.code:
                    service.code = f'SRV{service.id}'
                    service.save(update_fields=['code'])
                    self.stdout.write('       → Fixed: Generated service code')
                    fixed = True

        if fixed:
            self.stdout.write(
                self.style.SUCCESS('       ✓ Some issues fixed')
            )