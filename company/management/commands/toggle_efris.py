from django.core.management.base import BaseCommand
from company.models import Company


class Command(BaseCommand):
    help = 'Toggle EFRIS enabled status for a company'
    
    def add_arguments(self, parser):
        parser.add_argument('company_id', type=str, help='Company ID')
        parser.add_argument('--enable', action='store_true', help='Enable EFRIS')
        parser.add_argument('--disable', action='store_true', help='Disable EFRIS')
    
    def handle(self, *args, **options):
        company_id = options['company_id']
        
        try:
            company = Company.objects.get(company_id=company_id)
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Company {company_id} not found'))
            return
        
        if options['enable']:
            company.efris_enabled = True
            company.save()
            self.stdout.write(self.style.SUCCESS(f'EFRIS enabled for {company.name}'))
        elif options['disable']:
            company.efris_enabled = False
            company.save()
            self.stdout.write(self.style.SUCCESS(f'EFRIS disabled for {company.name}'))
        else:
            status = 'enabled' if company.efris_enabled else 'disabled'
            self.stdout.write(f'EFRIS is currently {status} for {company.name}')