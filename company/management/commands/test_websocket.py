from django.core.management.base import BaseCommand
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json


class Command(BaseCommand):
    help = 'Test WebSocket functionality'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=str, help='Company ID to test')

    def handle(self, *args, **options):
        company_id = options['company_id']
        if not company_id:
            self.stdout.write(self.style.ERROR('Please provide --company-id'))
            return

        channel_layer = get_channel_layer()

        if not channel_layer:
            self.stdout.write(self.style.ERROR('Channel layer not configured'))
            return

        try:
            # Test sending a message to company dashboard
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company_id}',
                {
                    'type': 'dashboard_update',
                    'data': {
                        'event_type': 'test_message',
                        'message': 'WebSocket test successful!',
                        'timestamp': '2024-01-01T00:00:00Z'
                    }
                }
            )

            self.stdout.write(
                self.style.SUCCESS(f'Test message sent to company {company_id}')
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error sending test message: {e}')
            )