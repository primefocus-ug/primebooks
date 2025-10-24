# from django.core.management.base import BaseCommand, CommandError
# from django.contrib.auth import get_user_model
# from efris.services.sync_service import EFRISSyncService
# from company.models import Company
#
# User = get_user_model()
#
#
# class Command(BaseCommand):
#     help = 'Sync data with EFRIS'
#
#     def add_arguments(self, parser):
#         parser.add_argument('--company-id', type=str, help='Company ID (if not provided, syncs all)')
#         parser.add_argument(
#             '--sync-type',
#             choices=['dictionary', 'goods', 'all'],
#             default='all',
#             help='Type of data to sync'
#         )
#         parser.add_argument('--force', action='store_true', help='Force sync even if recently synced')
#
#     def handle(self, *args, **options):
#         from django_tenants.utils import schema_context
#
#         try:
#             if options['company_id']:
#                 # Sync specific company
#                 with schema_context('public'):
#                     try:
#                         company = Company.objects.get(company_id=options['company_id'])
#                     except Company.DoesNotExist:
#                         raise CommandError(f"Company with ID {options['company_id']} not found")
#
#                 self._sync_company(company, options)
#
#             else:
#                 # Sync all companies
#                 with schema_context('public'):
#                     companies = Company.objects.filter(
#                         efris_enabled=True,
#                         is_active=True
#                     )
#
#                 for company in companies:
#                     try:
#                         self._sync_company(company, options)
#                     except Exception as e:
#                         self.stdout.write(
#                             self.style.ERROR(f"Failed to sync {company.display_name}: {e}")
#                         )
#
#         except Exception as e:
#             raise CommandError(f"Error syncing EFRIS data: {e}")
#
#     def _sync_company(self, company, options):
#         """Sync data for a specific company"""
#         from django_tenants.utils import schema_context
#
#         with schema_context(company.schema_name):
#             try:
#                 config = EFRISConfiguration.objects.filter(is_active=True).first()
#                 if not config:
#                     self.stdout.write(
#                         self.style.WARNING(f"No active EFRIS configuration for {company.display_name}")
#                     )
#                     return
#
#                 sync_service = EFRISSyncService(config)
#
#                 self.stdout.write(f"Syncing data for {company.display_name}...")
#
#                 total_synced = 0
#
#                 if options['sync_type'] in ['dictionary', 'all']:
#                     self.stdout.write("Syncing system dictionaries...")
#                     total_synced += sync_service.sync_all_dictionaries()
#
#                 if options['sync_type'] in ['goods', 'all']:
#                     self.stdout.write("Uploading pending goods...")
#                     total_synced += sync_service.upload_pending_goods()
#
#                 self.stdout.write(
#                     self.style.SUCCESS(
#                         f"Successfully synced {total_synced} items for {company.display_name}"
#                     )
#                 )
#
#             except Exception as e:
#                 raise CommandError(f"Error syncing {company.display_name}: {e}")
