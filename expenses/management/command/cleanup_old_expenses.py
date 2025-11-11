from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from expenses.models import Expense


class Command(BaseCommand):
    help = 'Cleanup old draft expenses and orphaned attachments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to keep draft expenses'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']

        cutoff_date = timezone.now() - timedelta(days=days)

        old_drafts = Expense.objects.filter(
            status='DRAFT',
            created_at__lte=cutoff_date
        )

        count = old_drafts.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'Would delete {count} draft expenses older than {days} days'
                )
            )
            for expense in old_drafts[:10]:
                self.stdout.write(f'  - {expense.expense_number}: {expense.title}')
            if count > 10:
                self.stdout.write(f'  ... and {count - 10} more')
        else:
            old_drafts.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully deleted {count} old draft expenses'
                )
            )