from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from errors.views import (
    error_403_view, error_404_view, error_500_view,
    error_502_view, error_503_view
)


class Command(BaseCommand):
    help = 'Test error pages'

    def add_arguments(self, parser):
        parser.add_argument(
            '--error-code',
            type=str,
            default='all',
            help='Specific error code to test (403, 404, 500, 502, 503) or "all"'
        )

    def handle(self, *args, **options):
        factory = RequestFactory()
        error_views = {
            '403': error_403_view,
            '404': error_404_view,
            '500': error_500_view,
            '502': error_502_view,
            '503': error_503_view,
        }

        error_code = options['error_code']

        if error_code == 'all':
            codes_to_test = error_views.keys()
        else:
            codes_to_test = [error_code] if error_code in error_views else []

        for code in codes_to_test:
            request = factory.get('/test/')
            request.user = AnonymousUser()

            try:
                response = error_views[code](request)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Error {code} page rendered successfully (Status: {response.status_code})'
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'✗ Error {code} page failed: {str(e)}')
                )

