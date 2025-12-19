from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import tenant_context
from company.models import Company as Tenant
from django.db import connection
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check and trigger scheduled reports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force run all active schedules now'
        )
        parser.add_argument(
            '--tenant',
            help='Run for specific tenant only',
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
                self.stdout.write(f"Checking schedules for tenant: {tenant.schema_name}")
                self.stdout.write(f"{'=' * 50}")

                now = timezone.now()

                # Get schedules
                schedules = ReportSchedule.objects.filter(is_active=True).select_related('report')

                self.stdout.write(f"Found {schedules.count()} active schedules")

                for schedule in schedules:
                    status = "❌ NO NEXT SCHEDULED" if not schedule.next_scheduled else (
                        "✅ DUE NOW" if schedule.next_scheduled <= now else "⏰ FUTURE"
                    )

                    self.stdout.write(f"\n• {schedule.report.name}")
                    self.stdout.write(f"  Status: {status}")
                    self.stdout.write(f"  Next run: {schedule.next_scheduled}")
                    self.stdout.write(f"  Frequency: {schedule.get_frequency_display()}")
                    self.stdout.write(f"  Last sent: {schedule.last_sent}")

                    # Force run if requested
                    if options['force']:
                        self.stdout.write(f"  🔧 Forcing execution now...")
                        try:
                            from reports.tasks import execute_schedule
                            execute_schedule.delay(schedule.id, tenant.schema_name)
                            self.stdout.write(f"  ✅ Execution triggered")
                        except Exception as e:
                            self.stdout.write(f"  ❌ Error: {e}")

                # Show which ones are due
                due_schedules = schedules.filter(next_scheduled__lte=now)
                if due_schedules.exists():
                    self.stdout.write(f"\n⚠️  {due_schedules.count()} schedules are due!")

                    # Trigger them
                    for schedule in due_schedules:
                        self.stdout.write(f"  Triggering: {schedule.report.name}")
                        from reports.tasks import execute_schedule
                        execute_schedule.delay(schedule.id, tenant.schema_name)