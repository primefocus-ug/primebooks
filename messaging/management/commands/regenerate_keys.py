from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django_tenants.utils import get_tenant_model, schema_context
from messaging.models import EncryptionKeyManager
from messaging.services import EncryptionService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Regenerate encryption keys for all users with new stable key method'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Regenerate keys for specific user ID only',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            help='Process specific tenant schema only',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        TenantModel = get_tenant_model()

        user_id = options.get('user_id')
        tenant_schema = options.get('tenant')

        # Get tenants to process
        if tenant_schema:
            tenants = TenantModel.objects.filter(schema_name=tenant_schema)
        else:
            tenants = TenantModel.objects.exclude(schema_name='public')

        total_regenerated = 0
        total_failed = 0

        for tenant in tenants:
            self.stdout.write(f"\nProcessing tenant: {tenant.schema_name}")

            with schema_context(tenant.schema_name):
                # Get users to process
                if user_id:
                    users = User.objects.filter(id=user_id)
                else:
                    users = User.objects.filter(is_active=True)

                for user in users:
                    try:
                        # Delete old keys
                        deleted_count = EncryptionKeyManager.objects.filter(user=user).delete()[0]

                        # Generate new keys with stable encryption
                        EncryptionService.generate_user_keys(user)

                        total_regenerated += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✓ Regenerated keys for user {user.id} ({user.username})'
                            )
                        )

                        if deleted_count > 0:
                            self.stdout.write(f'    (Deleted {deleted_count} old key record(s))')

                    except Exception as e:
                        total_failed += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f'  ✗ Failed for user {user.id} ({user.username}): {e}'
                            )
                        )
                        logger.error(f"Failed to regenerate keys for user {user.id}: {e}", exc_info=True)

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(f"Total regenerated: {total_regenerated}"))
        if total_failed > 0:
            self.stdout.write(self.style.ERROR(f"Total failed: {total_failed}"))
        self.stdout.write("=" * 50)

        if total_regenerated > 0:
            self.stdout.write(
                self.style.WARNING(
                    "\n⚠️  WARNING: All existing encrypted messages will be LOST "
                    "because the conversation keys were encrypted with the old user keys. "
                    "Users will need to create new conversations."
                )
            )