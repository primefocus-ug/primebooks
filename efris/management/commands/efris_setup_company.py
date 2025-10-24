from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from company.models import Company
from efris.services import EFRISConfigurationWizard
from efris.models import EFRISConfiguration


class Command(BaseCommand):
    help = 'Setup EFRIS configuration for a company (automatically in the tenant schema)'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=str, required=True, help='Company ID')
        parser.add_argument('--environment', choices=['sandbox', 'production'], default='sandbox')
        parser.add_argument('--mode', choices=['online', 'offline'], default='online')
        parser.add_argument('--device-mac', type=str, help='Device MAC address')

    def handle(self, *args, **options):
        company_id = options['company_id']
        environment = options['environment']
        mode = options['mode']
        device_mac = options.get('device_mac', 'FFFFFFFFFFFF')

        try:
            # Get the company first (on public schema)
            company = Company.objects.get(company_id=company_id)
            schema_name = company.schema_name

            # Run everything in the tenant's schema
            with schema_context(schema_name):
                self.stdout.write(f"Setting up EFRIS for company: {company.display_name} in schema {schema_name}")

                # Tenant-specific configuration
                config, created = EFRISConfiguration.objects.get_or_create(
                    company=company,
                    defaults={
                        'environment': environment,
                        'mode': mode,
                        'device_mac': device_mac,
                        'app_id': 'AP04',
                        'version': '1.1.20191201',
                        'timeout_seconds': 30,
                        'max_retry_attempts': 3,
                        'auto_sync_enabled': True,
                        'auto_fiscalize': True
                    }
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created new EFRIS configuration for {company.display_name}"))
                else:
                    self.stdout.write(f"Using existing EFRIS configuration for {company.display_name}")

                # Set API URL
                config.api_base_url = (
                    'https://efrisws.ura.go.ug/ws/taapp/getInformation'
                    if environment == 'production'
                    else 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'
                )
                config.save()

                # Run setup wizard
                wizard = EFRISConfigurationWizard(company)
                checklist = wizard.generate_setup_checklist()

                self.stdout.write("\n=== EFRIS Setup Checklist ===")
                self.stdout.write(f"Ready for production: {checklist['ready_for_production']}")
                self.stdout.write(f"Completion: {checklist['completion_percentage']:.1f}%")

                for item in checklist['checklist_items']:
                    status = "✓" if item['completed'] else "✗"
                    self.stdout.write(f"{status} {item['title']}: {item['description']}")

                if checklist['next_steps']:
                    self.stdout.write("\n=== Next Steps ===")
                    for step in checklist['next_steps']:
                        self.stdout.write(f"• {step}")

        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Company with ID '{company_id}' not found"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Setup failed: {e}"))
