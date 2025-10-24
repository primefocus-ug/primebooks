from django.core.management.base import BaseCommand
from django.db import transaction
from company.models import Company
from efris.services import setup_efris_for_company, EFRISConfigurationWizard

class Command(BaseCommand):
    help = 'Test EFRIS API connection for a company'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=str, required=True)

    def handle(self, *args, **options):
        company_id = options['company_id']

        try:
            company = Company.objects.get(company_id=company_id)
            self.stdout.write(f"Testing EFRIS connection for: {company.display_name}")

            # Test connection
            setup_result = setup_efris_for_company(company)

            if setup_result['success']:
                self.stdout.write(
                    self.style.SUCCESS("✓ EFRIS connection test successful")
                )

                for step in setup_result['steps_completed']:
                    self.stdout.write(f"✓ {step}")

                if setup_result.get('warnings'):
                    self.stdout.write("\n=== Warnings ===")
                    for warning in setup_result['warnings']:
                        self.stdout.write(self.style.WARNING(f"! {warning}"))

            else:
                self.stdout.write(
                    self.style.ERROR("✗ EFRIS connection test failed")
                )

                for error in setup_result.get('errors', []):
                    self.stdout.write(self.style.ERROR(f"✗ {error}"))

        except Company.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Company with ID '{company_id}' not found")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Connection test failed: {e}")
            )

