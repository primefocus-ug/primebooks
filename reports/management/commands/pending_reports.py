from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model, schema_context
from django.utils import timezone
from datetime import timedelta
from reports.models import GeneratedReport
import os

class Command(BaseCommand):
    help = "Cancel stale reports and remove expired ones for all tenants"

    def handle(self, *args, **options):
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.exclude(schema_name='public')  # skip public

        for tenant in tenants:
            self.stdout.write(f"Processing tenant: {tenant.schema_name}")

            with schema_context(tenant.schema_name):
                # Cancel stale PENDING / PROCESSING reports older than 1 day
                stale_time = timezone.now() - timedelta(days=0)
                stale_reports = GeneratedReport.objects.filter(
                    status__in=['PENDING', 'PROCESSING','CANCELLED','FAILED'],
                    generated_at__lt=stale_time
                )
                cancelled_count = stale_reports.update(
                    status='CANCELLED',
                    error_message='Cancelled due to inactivity/stuck state',
                    completed_at=timezone.now()
                )
                self.stdout.write(f"Cancelled {cancelled_count} stale reports")

                # Delete expired reports (and their files)
                expired_reports = GeneratedReport.objects.filter(
                    expires_at__lt=timezone.now()
                )
                for report in expired_reports:
                    if report.file_path and os.path.exists(report.file_path):
                        try:
                            os.remove(report.file_path)
                        except Exception as e:
                            self.stderr.write(f"Failed to delete {report.file_path}: {e}")
                    report.delete()
                self.stdout.write(f"Deleted {expired_reports.count()} expired reports")
