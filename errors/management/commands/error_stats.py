# management/commands/error_stats.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from errors.models import ErrorLog


class Command(BaseCommand):
    help = 'Show error statistics'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to analyze (default: 7)'
        )

    def handle(self, *args, **options):
        days = options['days']
        since = timezone.now() - timedelta(days=days)

        errors = ErrorLog.objects.filter(timestamp__gte=since)
        total_errors = errors.count()

        if total_errors == 0:
            self.stdout.write(
                self.style.SUCCESS(f'No errors in the last {days} days! 🎉')
            )
            return

        # Group by error code
        error_counts = {}
        for error in errors:
            code = error.error_code
            error_counts[code] = error_counts.get(code, 0) + 1

        self.stdout.write(f'\n📊 Error Statistics (Last {days} days)')
        self.stdout.write('=' * 50)
        self.stdout.write(f'Total Errors: {total_errors}')
        self.stdout.write('\nBreakdown by Error Code:')

        for code, count in sorted(error_counts.items()):
            percentage = (count / total_errors) * 100
            self.stdout.write(f'  {code}: {count} ({percentage:.1f}%)')

        # Most common paths
        self.stdout.write('\nMost Common Error Paths:')
        path_counts = {}
        for error in errors:
            path = error.path
            path_counts[path] = path_counts.get(path, 0) + 1

        top_paths = sorted(path_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        for path, count in top_paths:
            self.stdout.write(f'  {path}: {count} errors')