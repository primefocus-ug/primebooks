from django.core.management.base import BaseCommand
from efris.services import EnhancedEFRISAPIClient
from company.models import Company


class Command(BaseCommand):
    help = 'Sync EFRIS system dictionaries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            type=int,
            help='Sync dictionaries for specific company'
        )

    def handle(self, *args, **options):
        if options['company_id']:
            self._sync_company(options['company_id'])
        else:
            self._sync_all_companies()

    def _sync_company(self, company_id: int):
        try:
            company = Company.objects.get(pk=company_id)

            if not company.efris_enabled:
                self.stdout.write(
                    self.style.WARNING(f'EFRIS not enabled for {company.display_name}')
                )
                return

            self.stdout.write(f'Syncing dictionaries for: {company.display_name}')

            with EnhancedEFRISAPIClient(company) as client:
                response = client.get_system_dictionary()

                if response.success:
                    self.stdout.write(
                        self.style.SUCCESS('✓ Dictionaries synced successfully')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Sync failed: {response.error_message}')
                    )

        except Company.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Company {company_id} not found')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Sync failed: {e}')
            )

    def _sync_all_companies(self):
        companies = Company.objects.filter(efris_enabled=True, is_active=True)

        successful = 0
        failed = 0

        for company in companies:
            try:
                self.stdout.write(f'Syncing: {company.display_name}')

                with EnhancedEFRISAPIClient(company) as client:
                    response = client.get_system_dictionary()

                    if response.success:
                        successful += 1
                        self.stdout.write(
                            self.style.SUCCESS('  ✓ Success')
                        )
                    else:
                        failed += 1
                        self.stdout.write(
                            self.style.ERROR(f'  ✗ Failed: {response.error_message}')
                        )

            except Exception as e:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error: {e}')
                )

        self.stdout.write(f'\nCompleted: {successful} successful, {failed} failed')
