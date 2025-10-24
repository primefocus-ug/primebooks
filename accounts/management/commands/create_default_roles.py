from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from company.models import Company
from accounts.signals import create_default_roles_for_tenant
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create default roles for all existing tenants'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            help='Create roles for a specific tenant (schema_name)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreation of roles even if they exist',
        )

    def handle(self, *args, **options):
        tenant_schema = options.get('tenant')
        force = options.get('force', False)

        if tenant_schema:
            # Run for one tenant
            try:
                tenant = Company.objects.get(schema_name=tenant_schema)
                self.create_roles_for_tenant(tenant, force)
            except Company.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Tenant with schema "{tenant_schema}" not found')
                )
                return
        else:
            # Run for all tenants
            tenants = Company.objects.exclude(schema_name='public')
            self.stdout.write(self.style.SUCCESS(f'Found {tenants.count()} tenants'))

            for tenant in tenants:
                self.create_roles_for_tenant(tenant, force)

        self.stdout.write(self.style.SUCCESS('\nDefault role creation completed!'))

    def create_roles_for_tenant(self, tenant, force=False):
        """Create default roles for a single tenant"""
        self.stdout.write(f'\nProcessing tenant: {tenant.name} ({tenant.schema_name})')

        with schema_context(tenant.schema_name):
            from accounts.models import Role

            existing_roles = Role.objects.count()

            if existing_roles > 0 and not force:
                self.stdout.write(
                    self.style.WARNING(
                        f'  → Skipping: {existing_roles} roles already exist. '
                        f'Use --force to recreate.'
                    )
                )
                return

            if force and existing_roles > 0:
                self.stdout.write(
                    self.style.WARNING(f'  → Deleting {existing_roles} existing roles...')
                )
                Role.objects.all().delete()

            try:
                create_default_roles_for_tenant(
                    sender=Company,
                    instance=tenant,
                    created=True
                )

                created_count = Role.objects.count()
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ Created {created_count} default roles for {tenant.name}'
                    )
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ✗ Error creating roles for {tenant.name}: {str(e)}'
                    )
                )
                logger.exception(f"Error creating roles for tenant {tenant.schema_name}")
