from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import tenant_context
from company.models import Company as Tenant
from reports.tasks import process_scheduled_reports
import logging
from django.db import transaction

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
        parser.add_argument(
            '--force-run',
            action='store_true',
            help='Force run all active schedules immediately (bypasses schedule timing)',
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

                # Option 1: Set all schedules to run now
                if options['now']:
                    with transaction.atomic():
                        schedules = ReportSchedule.objects.filter(is_active=True)
                        count = schedules.count()
                        now = timezone.now()
                        # Use update() for bulk operation
                        schedules.update(next_scheduled=now)
                        self.stdout.write(f"✅ Set {count} schedules to run NOW ({now})")

                    # Refresh the queryset after update
                    due_schedules = ReportSchedule.objects.filter(
                        is_active=True,
                        next_scheduled__lte=timezone.now()
                    )

                # Option 2: Force run ALL active schedules immediately (regardless of next_scheduled)
                elif options['force_run']:
                    active_schedules = ReportSchedule.objects.filter(is_active=True)
                    self.stdout.write(f"\n⚡ FORCE RUNNING {active_schedules.count()} active schedules:")

                    for schedule in active_schedules:
                        self.stdout.write(f"\n🎯 Force Processing: {schedule.report.name}")
                        self.stdout.write(f"   Current next run: {schedule.next_scheduled}")
                        self.stdout.write(f"   Recipients: {schedule.recipients}")

                    # Trigger immediate processing
                    if active_schedules.exists():
                        self.stdout.write(f"\n🚀 Triggering process_scheduled_reports task for force run...")
                        process_scheduled_reports.delay()
                        self.stdout.write(f"✅ Force run task submitted to Celery")
                        continue  # Skip normal processing
                    else:
                        self.stdout.write(f"\n⚠️  No active schedules found")
                        continue

                # Normal processing (without --now or --force-run)
                else:
                    due_schedules = ReportSchedule.objects.filter(
                        is_active=True,
                        next_scheduled__lte=timezone.now()
                    )

                self.stdout.write(f"\nFound {due_schedules.count()} due schedules")

                # Display due schedules
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
                if all_schedules.exists():
                    self.stdout.write(f"\n📋 All active schedules:")
                    for s in all_schedules:
                        now = timezone.now()
                        time_diff = (s.next_scheduled - now).total_seconds() if s.next_scheduled else None
                        if time_diff is not None:
                            status = f"({abs(time_diff):.0f} seconds {'ago' if time_diff < 0 else 'from now'})"
                        else:
                            status = "(no schedule)"
                        self.stdout.write(f"   • {s.report.name}: {s.next_scheduled} {status}")