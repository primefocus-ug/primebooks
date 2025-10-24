from django.core.management.base import BaseCommand
from efris.automation import EFRISHealthChecker
from company.models import Company
import json


class Command(BaseCommand):
    help = 'Run EFRIS health check for companies'

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            type=int,
            help='Check specific company'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format'
        )

    def handle(self, *args, **options):
        if options['company_id']:
            self._check_company(options['company_id'], options['format'])
        else:
            self._check_all_companies(options['format'])

    def _check_company(self, company_id: int, format_type: str):
        try:
            company = Company.objects.get(pk=company_id)
            checker = EFRISHealthChecker(company)
            health_status = checker.check_system_health()

            if format_type == 'json':
                self.stdout.write(json.dumps(health_status, indent=2, default=str))
            else:
                self._display_health_table([health_status])

        except Company.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Company {company_id} not found')
            )

    def _check_all_companies(self, format_type: str):
        companies = Company.objects.filter(efris_enabled=True, is_active=True)
        health_results = []

        for company in companies:
            try:
                checker = EFRISHealthChecker(company)
                health_status = checker.check_system_health()
                health_status['company_name'] = company.display_name
                health_results.append(health_status)
            except Exception as e:
                health_results.append({
                    'company_id': company.pk,
                    'company_name': company.display_name,
                    'overall_status': 'error',
                    'error': str(e)
                })

        if format_type == 'json':
            self.stdout.write(json.dumps(health_results, indent=2, default=str))
        else:
            self._display_health_table(health_results)

    def _display_health_table(self, health_results):
        """Display health results in table format"""
        self.stdout.write('\nEFRIS Health Check Results')
        self.stdout.write('=' * 60)

        for result in health_results:
            company_name = result.get('company_name', f"Company {result.get('company_id')}")
            status = result.get('overall_status', 'unknown')

            if status == 'healthy':
                status_display = self.style.SUCCESS('✓ HEALTHY')
            elif status == 'degraded':
                status_display = self.style.WARNING('⚠ DEGRADED')
            else:
                status_display = self.style.ERROR('✗ UNHEALTHY')

            self.stdout.write(f'{company_name:<30} {status_display}')

            # Show check details
            checks = result.get('checks', {})
            for check_name, check_result in checks.items():
                if not check_result.get('healthy', True):
                    error = check_result.get('error', 'Unknown error')
                    self.stdout.write(f'  └─ {check_name}: {error}')

        self.stdout.write('')

