from django.core.management.base import BaseCommand
from django.utils import timezone
from efris.automation import EFRISAutomationManager, EFRISScheduler
from company.models import Company
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run EFRIS automation for companies'

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            type=int,
            help='Run automation for specific company'
        )
        parser.add_argument(
            '--setup-scheduler',
            action='store_true',
            help='Setup periodic task scheduler'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without executing'
        )

    def handle(self, *args, **options):
        if options['setup_scheduler']:
            self.stdout.write('Setting up EFRIS periodic tasks...')
            EFRISScheduler.setup_periodic_tasks()
            self.stdout.write(
                self.style.SUCCESS('Successfully setup EFRIS periodic tasks')
            )
            return

        if options['company_id']:
            self._run_for_company(options['company_id'], options['dry_run'])
        else:
            self._run_for_all_companies(options['dry_run'])

    def _run_for_company(self, company_id: int, dry_run: bool):
        try:
            company = Company.objects.get(pk=company_id)

            if not company.efris_enabled:
                self.stdout.write(
                    self.style.WARNING(f'EFRIS not enabled for {company.display_name}')
                )
                return

            if dry_run:
                self.stdout.write(f'Would process EFRIS automation for: {company.display_name}')
                return

            self.stdout.write(f'Processing EFRIS automation for: {company.display_name}')

            automation_manager = EFRISAutomationManager(company)
            results = automation_manager.process_pending_operations()

            self.stdout.write(
                self.style.SUCCESS(f'Automation completed: {results}')
            )

        except Company.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Company {company_id} not found')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Automation failed: {e}')
            )

    def _run_for_all_companies(self, dry_run: bool):
        companies = Company.objects.filter(
            efris_enabled=True,
            is_active=True
        )

        if dry_run:
            self.stdout.write(f'Would process {companies.count()} companies:')
            for company in companies:
                self.stdout.write(f'  - {company.display_name}')
            return

        processed = 0
        successful = 0

        for company in companies:
            try:
                self.stdout.write(f'Processing: {company.display_name}')

                automation_manager = EFRISAutomationManager(company)
                results = automation_manager.process_pending_operations()

                processed += 1

                # Consider successful if any operation succeeded
                if any(r.get('successful', 0) > 0 for r in results.values()):
                    successful += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Completed: {results}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'  ! No operations processed: {results}')
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Failed: {e}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nProcessed {processed} companies, {successful} successful'
            )
        )

