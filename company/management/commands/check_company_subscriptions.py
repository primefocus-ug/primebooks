from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db.models import Q
from django.core.mail import send_mail, send_mass_mail
from django.conf import settings
from company.models import Company
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check company subscriptions and update access status'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--company-id',
            type=str,
            help='Check specific company by ID',
        )
        parser.add_argument(
            '--send-notifications',
            action='store_true',
            help='Send email notifications to affected companies',
        )
        parser.add_argument(
            '--warning-days',
            type=int,
            nargs='+',
            default=[7, 3, 1],
            help='Days before expiration to send warnings (default: 7 3 1)',
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.send_notifications = options['send_notifications']
        self.warning_days = options['warning_days']

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        # Process specific company or all companies
        if options['company_id']:
            companies = Company.objects.filter(company_id=options['company_id'])
            if not companies.exists():
                raise CommandError(f"Company {options['company_id']} not found")
        else:
            companies = Company.objects.all()

        # Statistics
        stats = {
            'checked': 0,
            'updated': 0,
            'deactivated': 0,
            'warnings_sent': 0,
            'errors': 0
        }

        # Check and update company statuses
        self._check_company_statuses(companies, stats)

        # Send expiration warnings
        if self.send_notifications:
            self._send_expiration_warnings(stats)

        # Display summary
        self._display_summary(stats)

    def _check_company_statuses(self, companies, stats):
        """Check and update company access statuses"""
        self.stdout.write("Checking company access statuses...")

        for company in companies:
            stats['checked'] += 1

            try:
                old_status = company.status
                old_is_active = company.is_active

                if not self.dry_run:
                    status_changed = company.check_and_update_access_status()
                else:
                    # Simulate the check without saving
                    company.check_and_update_access_status()
                    status_changed = (old_status != company.status or old_is_active != company.is_active)
                    # Reset changes since we're in dry run
                    company.status = old_status
                    company.is_active = old_is_active

                if status_changed:
                    stats['updated'] += 1

                    if not company.is_active and old_is_active:
                        stats['deactivated'] += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"🔴 DEACTIVATED: {company.company_id} ({company.display_name}) "
                                f"- {old_status} → {company.status}"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"🟡 UPDATED: {company.company_id} ({company.display_name}) "
                                f"- {old_status} → {company.status}"
                            )
                        )

                # Log companies in grace period
                if company.is_in_grace_period:
                    days_left = (company.grace_period_ends_at - timezone.now().date()).days
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  GRACE PERIOD: {company.company_id} ({company.display_name}) "
                            f"- {days_left} days left"
                        )
                    )

            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error processing company {company.company_id}: {str(e)}")
                self.stdout.write(
                    self.style.ERROR(f"❌ ERROR: {company.company_id} - {str(e)}")
                )

    def _send_expiration_warnings(self, stats):
        """Send expiration warning emails"""
        self.stdout.write("Sending expiration warnings...")

        today = timezone.now().date()
        messages_to_send = []

        for warning_days in self.warning_days:
            warning_date = today + timedelta(days=warning_days)

            # Find companies expiring on warning date
            expiring_companies = Company.objects.filter(
                is_active=True,
                status__in=['ACTIVE', 'TRIAL']
            ).filter(
                Q(is_trial=True, trial_ends_at=warning_date) |
                Q(is_trial=False, subscription_ends_at=warning_date)
            )

            for company in expiring_companies:
                try:
                    if not self.dry_run:
                        subject, message, recipients = self._prepare_warning_email(company, warning_days)
                        messages_to_send.append((subject, message, settings.DEFAULT_FROM_EMAIL, recipients))

                    stats['warnings_sent'] += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"📧 WARNING SENT: {company.company_id} ({company.display_name}) "
                            f"- {warning_days} days to expiry"
                        )
                    )

                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"Error preparing warning email for {company.company_id}: {str(e)}")

        # Send all emails at once
        if messages_to_send and not self.dry_run:
            try:
                send_mass_mail(messages_to_send, fail_silently=False)
                self.stdout.write(self.style.SUCCESS(f"Sent {len(messages_to_send)} warning emails"))
            except Exception as e:
                logger.error(f"Error sending warning emails: {str(e)}")
                self.stdout.write(self.style.ERROR(f"Failed to send warning emails: {str(e)}"))

    def _prepare_warning_email(self, company, days):
        """Prepare warning email content"""
        expiry_type = "trial" if company.is_trial else "subscription"
        expiry_date = company.trial_ends_at if company.is_trial else company.subscription_ends_at

        subject = f"Your {expiry_type} expires in {days} day{'s' if days != 1 else ''}"

        message = f"""
Dear {company.display_name},

Your {expiry_type} will expire in {days} day{'s' if days != 1 else ''} on {expiry_date}.

Company Details:
- Company ID: {company.company_id}
- Current Plan: {company.plan.display_name if company.plan else 'N/A'}
- Expiry Date: {expiry_date}

To avoid service interruption, please renew your subscription before the expiry date.

You can manage your subscription at: {company.get_absolute_url()}/billing/

If you have any questions, please contact our support team.

Best regards,
The Support Team
        """.strip()

        recipients = [email for email in [company.email, company.billing_email] if email]

        return subject, message, recipients

    def _display_summary(self, stats):
        """Display command execution summary"""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("EXECUTION SUMMARY"))
        self.stdout.write("=" * 60)

        self.stdout.write(f"📊 Companies checked: {stats['checked']}")
        self.stdout.write(f"🔄 Status updates: {stats['updated']}")
        self.stdout.write(f"🔴 Deactivated: {stats['deactivated']}")

        if self.send_notifications:
            self.stdout.write(f"📧 Warning emails sent: {stats['warnings_sent']}")

        if stats['errors'] > 0:
            self.stdout.write(self.style.ERROR(f"❌ Errors encountered: {stats['errors']}"))

        if self.dry_run:
            self.stdout.write(self.style.WARNING("\n⚠️  This was a DRY RUN - no actual changes were made"))
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ Command completed successfully"))


# Example crontab entries:

"""
# Add these to your crontab (crontab -e) for automated execution:

# Check company subscriptions every 6 hours
0 */6 * * * /path/to/your/project/manage.py check_company_subscriptions --send-notifications

# Daily check at 2 AM with detailed logging
0 2 * * * /path/to/your/project/manage.py check_company_subscriptions --send-notifications >> /var/log/company_checks.log 2>&1

# Dry run check every hour during business hours (for monitoring)
0 9-17 * * 1-5 /path/to/your/project/manage.py check_company_subscriptions --dry-run
"""


