from django.core.management.base import BaseCommand
from company.models import Company
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check and update company access status based on subscriptions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )
        parser.add_argument(
            '--company-id',
            type=str,
            help='Check specific company by ID',
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        company_id = options.get('company_id')

        if company_id:
            companies = Company.objects.filter(company_id=company_id)
        else:
            companies = Company.objects.all()

        total_checked = 0
        total_updated = 0
        total_deactivated = 0

        for company in companies:
            total_checked += 1

            old_status = company.status
            old_is_active = company.is_active

            if self.dry_run:
                # Just check without saving
                company.check_and_update_access_status()
                company.refresh_from_db()  # Reset changes
            else:
                status_changed = company.check_and_update_access_status()

                if status_changed:
                    total_updated += 1
                    if not company.is_active and old_is_active:
                        total_deactivated += 1

                    self.stdout.write(
                        self.style.WARNING(
                            f"Company {company.company_id} ({company.display_name}): "
                            f"{old_status} -> {company.status}, "
                            f"Active: {old_is_active} -> {company.is_active}"
                        )
                    )

        # Summary
        if self.dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: Checked {total_checked} companies. "
                    "Use --no-dry-run to apply changes."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed {total_checked} companies. "
                    f"Updated {total_updated}, Deactivated {total_deactivated}."
                )
            )

