# Testing ReportSchedule with django-tenants
# Run this in Django shell: python manage.py shell

from django_tenants.utils import schema_context, tenant_context
from company.models import Company
from reports.models import ReportSchedule, SavedReport
from django.utils import timezone
import datetime

# Get the tenant (Company with schema_name='pada')
tenant = Company.objects.get(schema_name='pada')

# Run all tests within the tenant's schema context
with tenant_context(tenant):
    print(f"=== Testing ReportSchedule in tenant: {tenant.schema_name} ===\n")

    # Get a saved report
    report = SavedReport.objects.first()

    if not report:
        print("ERROR: No SavedReport found in this tenant's schema!")
        print("Create a saved report first before running these tests.")
    else:
        print(f"Using report: {report.name} (ID: {report.id})\n")

        # Test 1: HOURLY
        print("=" * 60)
        print("TEST 1: HOURLY Schedule")
        print("=" * 60)
        try:
            schedule = ReportSchedule.objects.create(
                report=report,
                frequency='HOURLY',
                recipients='test@example.com',
                format='PDF'
            )
            print(f"✓ Created HOURLY schedule")
            print(f"  ID: {schedule.id}")
            print(f"  Next run: {schedule.next_scheduled}")
            print(f"  Expected: ~1 hour from now")
            print(f"  Difference: {(schedule.next_scheduled - timezone.now()).total_seconds() / 60:.1f} minutes\n")
        except Exception as e:
            print(f"✗ ERROR creating HOURLY schedule: {e}\n")

        # Test 2: DAILY
        print("=" * 60)
        print("TEST 2: DAILY Schedule (10:30 AM)")
        print("=" * 60)
        try:
            schedule = ReportSchedule.objects.create(
                report=report,
                frequency='DAILY',
                time_of_day=datetime.time(10, 30),
                recipients='test@example.com',
                format='PDF'
            )
            print(f"✓ Created DAILY schedule")
            print(f"  ID: {schedule.id}")
            print(f"  Next run: {schedule.next_scheduled}")
            print(f"  Time of day: {schedule.time_of_day}")
            print(f"  Expected: Today or tomorrow at 10:30 AM\n")
        except Exception as e:
            print(f"✗ ERROR creating DAILY schedule: {e}\n")

        # Test 3: WEEKLY
        print("=" * 60)
        print("TEST 3: WEEKLY Schedule (Every Monday at 9:00 AM)")
        print("=" * 60)
        try:
            schedule = ReportSchedule.objects.create(
                report=report,
                frequency='WEEKLY',
                day_of_week=0,  # Monday
                time_of_day=datetime.time(9, 0),
                recipients='test@example.com',
                format='PDF'
            )
            print(f"✓ Created WEEKLY schedule")
            print(f"  ID: {schedule.id}")
            print(f"  Next run: {schedule.next_scheduled}")
            print(f"  Day of week: {schedule.get_day_of_week_display()}")
            print(f"  Time of day: {schedule.time_of_day}")
            print(f"  Expected: Next Monday at 9:00 AM\n")
        except Exception as e:
            print(f"✗ ERROR creating WEEKLY schedule: {e}\n")

        # Test 4: MONTHLY
        print("=" * 60)
        print("TEST 4: MONTHLY Schedule (15th of each month at 8:00 AM)")
        print("=" * 60)
        try:
            schedule = ReportSchedule.objects.create(
                report=report,
                frequency='MONTHLY',
                day_of_month=15,
                time_of_day=datetime.time(8, 0),
                recipients='test@example.com',
                format='PDF'
            )
            print(f"✓ Created MONTHLY schedule")
            print(f"  ID: {schedule.id}")
            print(f"  Next run: {schedule.next_scheduled}")
            print(f"  Day of month: {schedule.day_of_month}")
            print(f"  Time of day: {schedule.time_of_day}")
            print(f"  Expected: 15th of this/next month at 8:00 AM\n")
        except Exception as e:
            print(f"✗ ERROR creating MONTHLY schedule: {e}\n")

        # Test 5: QUARTERLY
        print("=" * 60)
        print("TEST 5: QUARTERLY Schedule")
        print("=" * 60)
        try:
            schedule = ReportSchedule.objects.create(
                report=report,
                frequency='QUARTERLY',
                time_of_day=datetime.time(9, 0),
                recipients='test@example.com',
                format='PDF'
            )
            print(f"✓ Created QUARTERLY schedule")
            print(f"  ID: {schedule.id}")
            print(f"  Next run: {schedule.next_scheduled}")
            print(f"  Expected: ~3 months from now\n")
        except Exception as e:
            print(f"✗ ERROR creating QUARTERLY schedule: {e}\n")

        # Test 6: YEARLY
        print("=" * 60)
        print("TEST 6: YEARLY Schedule")
        print("=" * 60)
        try:
            schedule = ReportSchedule.objects.create(
                report=report,
                frequency='YEARLY',
                time_of_day=datetime.time(9, 0),
                recipients='test@example.com',
                format='PDF'
            )
            print(f"✓ Created YEARLY schedule")
            print(f"  ID: {schedule.id}")
            print(f"  Next run: {schedule.next_scheduled}")
            print(f"  Expected: 1 year from now\n")
        except Exception as e:
            print(f"✗ ERROR creating YEARLY schedule: {e}\n")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        all_schedules = ReportSchedule.objects.all()
        print(f"Total schedules in '{tenant.schema_name}': {all_schedules.count()}")
        print("\nAll schedules:")
        for sch in all_schedules:
            print(f"  - {sch.report.name} ({sch.get_frequency_display()})")
            print(f"    Next run: {sch.next_scheduled}")
            print(f"    Active: {sch.is_active}")
            print()

print("\n" + "=" * 60)
print("Testing complete!")
print("=" * 60)