# primebooks/management/commands/sync_data.py
"""
Management command to trigger sync manually
Usage: python manage.py sync_data --tenant-id 1
"""
from django.core.management.base import BaseCommand
from primebooks.sync import SyncManager


class Command(BaseCommand):
    help = 'Sync data between desktop and server'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=int, required=True)

    def handle(self, *args, **options):
        tenant_id = options['tenant_id']

        self.stdout.write(f"Syncing tenant {tenant_id}...")

        sync_manager = SyncManager(tenant_id)

        if sync_manager.is_online():
            success = sync_manager.full_sync()
            if success:
                self.stdout.write(self.style.SUCCESS('Sync completed successfully'))
            else:
                self.stdout.write(self.style.ERROR('Sync failed'))
        else:
            self.stdout.write(self.style.WARNING('Server not reachable'))