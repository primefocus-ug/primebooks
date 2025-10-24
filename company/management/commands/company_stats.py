from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Q
from company.models import Company, SubscriptionPlan
from accounts.models import CustomUser
from datetime import timedelta


class Command(BaseCommand):
    help = 'Display company statistics and health metrics'

    def add_arguments(self, parser):
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed breakdown by plan and status',
        )
        parser.add_argument(
            '--export-csv',
            type=str,
            help='Export statistics to CSV file',
        )

    def handle(self, *args, **options):
        self.detailed = options['detailed']
        self.export_csv = options.get('export_csv')

        self._display_overview()

        if self.detailed:
            self._display_detailed_stats()

        self._display_health_metrics()

        if self.export_csv:
            self._export_to_csv()

    def _display_overview(self):
        """Display overview statistics"""
        total_companies = Company.objects.count()

        stats = Company.objects.aggregate(
            active=Count('company_id', filter=Q(status='ACTIVE')),
            trial=Count('company_id', filter=Q(status='TRIAL')),
            suspended=Count('company_id', filter=Q(status='SUSPENDED')),
            expired=Count('company_id', filter=Q(status='EXPIRED')),
            archived=Count('company_id', filter=Q(status='ARCHIVED')),
        )

        self.stdout.write(self.style.SUCCESS("📊 COMPANY OVERVIEW"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"Total Companies: {total_companies}")
        self.stdout.write(f"Active: {stats['active']} ({self._percentage(stats['active'], total_companies)}%)")
        self.stdout.write(f"Trial: {stats['trial']} ({self._percentage(stats['trial'], total_companies)}%)")
        self.stdout.write(f"Suspended: {stats['suspended']} ({self._percentage(stats['suspended'], total_companies)}%)")
        self.stdout.write(f"Expired: {stats['expired']} ({self._percentage(stats['expired'], total_companies)}%)")
        self.stdout.write(f"Archived: {stats['archived']} ({self._percentage(stats['archived'], total_companies)}%)")

    def _display_detailed_stats(self):
        """Display detailed statistics breakdown"""
        self.stdout.write(f"\n{self.style.SUCCESS('📋 DETAILED BREAKDOWN')}")
        self.stdout.write("=" * 50)

        # By subscription plan
        self.stdout.write("\nBy Subscription Plan:")
        for plan in SubscriptionPlan.objects.all():
            count = Company.objects.filter(plan=plan).count()
            self.stdout.write(f"  {plan.display_name or plan.get_name_display()}: {count}")

        # By creation date
        self.stdout.write("\nBy Registration Period:")
        today = timezone.now().date()
        periods = [
            ("Last 7 days", today - timedelta(days=7)),
            ("Last 30 days", today - timedelta(days=30)),
            ("Last 90 days", today - timedelta(days=90)),
        ]

        for period_name, start_date in periods:
            count = Company.objects.filter(created_at__gte=start_date).count()
            self.stdout.write(f"  {period_name}: {count}")

    def _display_health_metrics(self):
        """Display system health metrics"""
        self.stdout.write(f"\n{self.style.WARNING('⚡ HEALTH METRICS')}")
        self.stdout.write("=" * 50)

        today = timezone.now().date()

        # Companies needing attention
        expiring_soon = Company.objects.filter(
            is_active=True,
            status__in=['ACTIVE', 'TRIAL']
        ).filter(
            Q(trial_ends_at__lte=today + timedelta(days=7), is_trial=True) |
            Q(subscription_ends_at__lte=today + timedelta(days=7), is_trial=False)
        ).count()

        in_grace = Company.objects.filter(
            status='SUSPENDED',
            grace_period_ends_at__gte=today
        ).count()

        overdue = Company.objects.filter(
            status='EXPIRED'
        ).count()

        self.stdout.write(f"⚠️  Expiring within 7 days: {expiring_soon}")
        self.stdout.write(f"⏳ In grace period: {in_grace}")
        self.stdout.write(f"🔴 Overdue/Expired: {overdue}")

        # User statistics
        total_users = CustomUser.objects.count()
        active_users = CustomUser.objects.filter(is_active=True).count()

        self.stdout.write(f"\n👥 Users: {active_users}/{total_users} active")

    def _percentage(self, part, total):
        """Calculate percentage"""
        return round((part / total * 100), 1) if total > 0 else 0

    def _export_to_csv(self):
        """Export statistics to CSV file"""
        import csv

        with open(self.export_csv, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Company ID', 'Name', 'Status', 'Plan', 'Expiry Date', 'Users'])

            for company in Company.objects.select_related('plan').all():
                expiry_date = company.trial_ends_at if company.is_trial else company.subscription_ends_at
                user_count = CustomUser.objects.filter(company=company).count()

                writer.writerow([
                    company.company_id,
                    company.display_name,
                    company.get_status_display(),
                    company.plan.display_name if company.plan else 'None',
                    expiry_date or 'N/A',
                    user_count
                ])

        self.stdout.write(self.style.SUCCESS(f"📄 Statistics exported to {self.export_csv}"))


# Usage examples:
"""
# Basic check (dry run)
python manage.py check_company_subscriptions --dry-run

# Full check with notifications
python manage.py check_company_subscriptions --send-notifications

# Check specific company
python manage.py check_company_subscriptions --company-id PF-N123456

# Custom warning schedule (15, 7, 3, 1 days before expiry)
python manage.py check_company_subscriptions --send-notifications --warning-days 15 7 3 1

# Display statistics
python manage.py company_stats

# Detailed statistics with CSV export
python manage.py company_stats --detailed --export-csv company_stats.csv
"""