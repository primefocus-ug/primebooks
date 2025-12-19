from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import tenant_context
from company.models import Company as Tenant
from reports.tasks import process_scheduled_reports  # Use this instead
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Force run scheduled reports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            help='Run for specific tenant only',
        )
        parser.add_argument(
            '--now',
            action='store_true',
            help='Set all schedules to run now',
        )

    def handle(self, *args, **options):
        from reports.models import ReportSchedule

        if options['tenant']:
            tenants = Tenant.objects.filter(schema_name=options['tenant'])
        else:
            tenants = Tenant.objects.filter(is_active=True).exclude(schema_name='public')

        for tenant in tenants:
            with tenant_context(tenant):
                self.stdout.write(f"\n{'=' * 50}")
                self.stdout.write(f"Processing schedules for tenant: {tenant.schema_name}")
                self.stdout.write(f"{'=' * 50}")

                # Optionally set all schedules to run now
                if options['now']:
                    schedules = ReportSchedule.objects.filter(is_active=True)
                    for schedule in schedules:
                        schedule.next_scheduled = timezone.now()
                        schedule.save()
                    self.stdout.write(f"Set {schedules.count()} schedules to run NOW")

                # Get due schedules
                due_schedules = ReportSchedule.objects.filter(
                    is_active=True,
                    next_scheduled__lte=timezone.now()
                )

                self.stdout.write(f"Found {due_schedules.count()} due schedules")

                for schedule in due_schedules:
                    self.stdout.write(f"\n🎯 Processing: {schedule.report.name}")
                    self.stdout.write(f"   Next run: {schedule.next_scheduled}")
                    self.stdout.write(f"   Recipients: {schedule.recipients}")

                # Trigger the main processing task
                if due_schedules.exists():
                    self.stdout.write(f"\n🚀 Triggering process_scheduled_reports task...")
                    process_scheduled_reports.delay()
                    self.stdout.write(f"✅ Task submitted to Celery")
                else:
                    self.stdout.write(f"\n⚠️  No due schedules found")

                    # Show all schedules for debugging
                    all_schedules = ReportSchedule.objects.filter(is_active=True)
                    self.stdout.write(f"\n📋 All active schedules:")
                    for s in all_schedules:
                        time_diff = (s.next_scheduled - timezone.now()).total_seconds() if s.next_scheduled else None
                        self.stdout.write(
                            f"   • {s.report.name}: {s.next_scheduled} ({time_diff:.0f} seconds from now)")