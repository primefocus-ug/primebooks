from django.core.management.base import BaseCommand
from django.utils import timezone
from invoices.models import Invoice
from invoices.tasks import send_payment_reminder

class Command(BaseCommand):
    help = 'Send payment reminders for overdue invoices'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days-overdue',
            type=int,
            default=1,
            help='Minimum days overdue to send reminder'
        )
    
    def handle(self, *args, **options):
        days_overdue = options['days_overdue']
        cutoff_date = timezone.now().date() - timezone.timedelta(days=days_overdue)
        
        overdue_invoices = Invoice.objects.filter(
            due_date__lte=cutoff_date,
            status__in=['SENT', 'PARTIALLY_PAID']
        )
        
        count = 0
        for invoice in overdue_invoices:
            send_payment_reminder.delay(invoice.id)
            count += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully queued payment reminders for {count} overdue invoices'
            )
        )

