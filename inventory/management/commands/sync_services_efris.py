from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context
from company.models import Company
from inventory.models import Service
from efris.services import bulk_register_services_with_efris, EFRISServiceManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync services with EFRIS for a specific tenant or all tenants'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            help='Schema name of the tenant (if not provided, runs for all tenants)',
        )

        parser.add_argument(
            '--service-id',
            type=int,
            help='Specific service ID to sync',
        )

        parser.add_argument(
            '--bulk',
            action='store_true',
            help='Run bulk sync for all pending services',
        )

        parser.add_argument(
            '--validate-only',
            action='store_true',
            help='Only validate services without syncing',
        )

        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sync even if already uploaded',
        )

    def handle(self, *args, **options):
        schema_name = options.get('schema')
        service_id = options.get('service_id')
        bulk = options.get('bulk')
        validate_only = options.get('validate_only')
        force = options.get('force')

        try:
            if schema_name:
                # Single tenant
                companies = [Company.objects.get(schema_name=schema_name)]
            else:
                # All tenants
                companies = Company.objects.filter(is_active=True)

            total_synced = 0
            total_failed = 0

            for company in companies:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n{"=" * 60}\nProcessing company: {company.name} ({company.schema_name})\n{"=" * 60}'
                    )
                )

                with schema_context(company.schema_name):
                    if service_id:
                        # Sync specific service
                        result = self._sync_single_service(
                            company, service_id, validate_only, force
                        )
                        if result['success']:
                            total_synced += 1
                        else:
                            total_failed += 1

                    elif bulk:
                        # Bulk sync
                        result = self._bulk_sync_services(
                            company, validate_only, force
                        )
                        total_synced += result['successful']
                        total_failed += result['failed']

                    else:
                        # Sync pending services
                        result = self._sync_pending_services(
                            company, validate_only, force
                        )
                        total_synced += result['successful']
                        total_failed += result['failed']

            # Summary
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n{"=" * 60}\nSummary:\n{"=" * 60}'
                )
            )
            self.stdout.write(f'Total synced: {total_synced}')
            self.stdout.write(f'Total failed: {total_failed}')

            if total_failed > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'\n⚠️  {total_failed} service(s) failed to sync. Check logs for details.'
                    )
                )

        except Company.DoesNotExist:
            raise CommandError(f'Company with schema "{schema_name}" does not exist')
        except Exception as e:
            raise CommandError(f'Error: {str(e)}')

    def _sync_single_service(self, company, service_id, validate_only, force):
        """Sync a single service"""
        try:
            service = Service.objects.get(id=service_id)

            self.stdout.write(f'\nService: {service.name} ({service.code})')

            manager = EFRISServiceManager(company)

            # Validate
            is_valid, errors = manager.validate_service_for_efris(service)

            if not is_valid:
                self.stdout.write(
                    self.style.ERROR(f'  ❌ Validation failed:')
                )
                for error in errors:
                    self.stdout.write(f'     - {error}')
                return {'success': False}

            if validate_only:
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ Validation passed')
                )
                return {'success': True}

            # Check if already uploaded
            if service.efris_is_uploaded and not force:
                self.stdout.write(
                    self.style.WARNING(f'  ⚠️  Already uploaded (use --force to re-sync)')
                )
                return {'success': True}

            # Sync
            if service.efris_is_uploaded:
                result = manager.update_service(service)
                operation = 'Updated'
            else:
                result = manager.register_service(service)
                operation = 'Registered'

            if result.get('success'):
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ {operation} successfully (EFRIS ID: {result.get("efris_service_id")})'
                    )
                )
                return {'success': True}
            else:
                self.stdout.write(
                    self.style.ERROR(f'  ❌ Failed: {result.get("error")}')
                )
                return {'success': False}

        except Service.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Service with ID {service_id} not found')
            )
            return {'success': False}
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ❌ Error: {str(e)}')
            )
            return {'success': False}

    def _bulk_sync_services(self, company, validate_only, force):
        """Bulk sync all services"""
        self.stdout.write('\nRunning bulk sync...')

        if validate_only:
            # Just validate
            services = Service.objects.filter(
                is_active=True,
                efris_auto_sync_enabled=True
            )

            manager = EFRISServiceManager(company)

            results = {'successful': 0, 'failed': 0}

            for service in services:
                is_valid, errors = manager.validate_service_for_efris(service)
                if is_valid:
                    results['successful'] += 1
                    self.stdout.write(f'  ✓ {service.name}')
                else:
                    results['failed'] += 1
                    self.stdout.write(f'  ❌ {service.name}: {"; ".join(errors)}')

            return results

        # Actual bulk sync
        results = bulk_register_services_with_efris(company)

        self.stdout.write(
            f'\nBulk sync completed:'
        )
        self.stdout.write(f'  Total: {results["total"]}')
        self.stdout.write(f'  Successful: {results["successful"]}')
        self.stdout.write(f'  Failed: {results["failed"]}')

        if results['errors']:
            self.stdout.write('\nErrors:')
            for error in results['errors'][:10]:  # Show first 10 errors
                self.stdout.write(
                    f'  - {error["service_name"]}: {error["error"]}'
                )

        return results

    def _sync_pending_services(self, company, validate_only, force):
        """Sync pending services"""
        # Get pending services
        queryset = Service.objects.filter(
            is_active=True,
            efris_auto_sync_enabled=True
        )

        if not force:
            queryset = queryset.filter(efris_is_uploaded=False)

        services = list(queryset)

        if not services:
            self.stdout.write(
                self.style.WARNING('No pending services to sync')
            )
            return {'successful': 0, 'failed': 0}

        self.stdout.write(f'\nFound {len(services)} pending service(s)')

        manager = EFRISServiceManager(company)

        results = {'successful': 0, 'failed': 0}

        for service in services:
            # Validate
            is_valid, errors = manager.validate_service_for_efris(service)

            if not is_valid:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ {service.name}: Validation failed - {"; ".join(errors)}'
                    )
                )
                results['failed'] += 1
                continue

            if validate_only:
                self.stdout.write(f'  ✓ {service.name}: Valid')
                results['successful'] += 1
                continue

            # Sync
            result = manager.sync_service_changes(service)

            if result.get('success'):
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ {service.name}: Synced')
                )
                results['successful'] += 1
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ {service.name}: {result.get("error")}'
                    )
                )
                results['failed'] += 1

        return results

