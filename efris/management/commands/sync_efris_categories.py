from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from company.models import Company
from efris.services import sync_commodity_categories


class Command(BaseCommand):
    help = 'Sync EFRIS commodity categories for a company'

    def add_arguments(self, parser):
        parser.add_argument('company_id', type=str, help='Company ID (string or int)')

    def handle(self, *args, **options):
        company_id = options['company_id']

        try:
            # If company_id is your primary key (string), use pk
            company = Company.objects.get(pk=company_id)

            self.stdout.write(f"Syncing categories for {company.name}...")

            with schema_context(company.schema_name):
                result = sync_commodity_categories(company)

                if result.get('success'):
                    total_saved = result.get('total_saved', 0)
                    total_fetched = result.get('total_fetched', 0)
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ Synced {total_saved}/{total_fetched} categories"
                    ))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"✗ Sync failed: {result.get('errors', 'Unknown error')}"
                    ))

        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Company {company_id} not found"))
