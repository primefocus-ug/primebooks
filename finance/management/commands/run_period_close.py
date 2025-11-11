from django.core.management.base import BaseCommand
from finance.utils.automation import FinanceAutomation
from finance.models import FiscalPeriod
from accounts.models import CustomUser


class Command(BaseCommand):
    help = 'Run period-end closing procedures'

    def add_arguments(self, parser):
        parser.add_argument('period_id', type=int, help='Fiscal Period ID')
        parser.add_argument('--user-id', type=int, required=True, help='User ID for audit')

    def handle(self, *args, **options):
        period = FiscalPeriod.objects.get(pk=options['period_id'])
        user = CustomUser.objects.get(pk=options['user_id'])

        self.stdout.write(f"Starting period close for {period}...")

        results = FinanceAutomation.run_period_end_close(period, user)

        self.stdout.write(self.style.SUCCESS(
            f"Period closed successfully!\n"
            f"Depreciation entries: {len(results['depreciation'])}\n"
            f"Recurring entries: {len(results['recurring_entries'])}\n"
            f"Errors: {len(results['errors'])}"
        ))

        if results['errors']:
            self.stdout.write(self.style.ERROR("Errors:"))
            for error in results['errors']:
                self.stdout.write(f"  - {error}")