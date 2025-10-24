from django.core.management.base import BaseCommand, CommandError
from company.models import Company
from django_tenants.utils import schema_context

class Command(BaseCommand):
    help = 'Setup EFRIS configuration for a company'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=str, required=True, help='Company ID')
        parser.add_argument('--tin', type=str, required=True, help='TIN Number')
        parser.add_argument('--name', type=str, required=True, help='Taxpayer Name')
        parser.add_argument('--trading-name', type=str, required=True, help='Business Name')
        parser.add_argument('--email', type=str, required=True, help='Email Address')
        parser.add_argument('--phone', type=str, required=True, help='Phone Number')
        parser.add_argument('--address', type=str, required=True, help='Business Address')
        parser.add_argument('--mode', choices=['online', 'offline'], default='offline', help='Integration Mode')
        parser.add_argument('--device-no', type=str, help='Device Number')
        parser.add_argument('--production', action='store_true', help='Setup for production environment')

    def handle(self, *args, **options):
        try:
            with schema_context('public'):
                try:
                    company = Company.objects.get(company_id=options['company_id'])
                except Company.DoesNotExist:
                    raise CommandError(f"Company with ID {options['company_id']} not found")

            # Switch to tenant schema
            with schema_context(company.schema_name):
                # Update EFRIS fields
                company.tin = options['tin']
                company.name = options['name']
                company.trading_name = options['trading_name']
                company.email = options['email']
                company.phone = options['phone']
                company.physical_address = options['address']
                company.efris_integration_mode = options['mode']
                company.efris_device_number = options.get('device_no')
                company.efris_is_production = options['production']
                company.efris_enabled = True
                company.efris_is_active = True
                company.save()

                self.stdout.write(self.style.SUCCESS(
                    f"EFRIS configuration set for company {company.display_name}"
                ))

                # Next steps
                self.stdout.write("Next steps:")
                self.stdout.write("1. Upload RSA certificate: python manage.py upload_efris_certificate")
                self.stdout.write("2. Register device: python manage.py register_efris_device")
                if options['mode'] == 'offline':
                    self.stdout.write("3. Install offline enabler app")
                self.stdout.write("4. Sync system dictionaries: python manage.py sync_efris_data")
                self.stdout.write("5. Upload goods: python manage.py upload_efris_goods")

        except Exception as e:
            raise CommandError(f"Error setting up EFRIS: {e}")
