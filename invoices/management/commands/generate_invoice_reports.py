from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Count
from invoices.models import Invoice
import csv
import os

class Command(BaseCommand):
    help = 'Generate monthly invoice reports'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            help='Month in YYYY-MM format (default: current month)'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            default='reports',
            help='Output directory for reports'
        )
    
    def handle(self, *args, **options):
        if options['month']:
            year, month = map(int, options['month'].split('-'))
            start_date = timezone.datetime(year, month, 1).date()
        else:
            now = timezone.now()
            start_date = now.replace(day=1).date()
        
        end_date = (start_date.replace(day=28) + timezone.timedelta(days=4)).replace(day=1) - timezone.timedelta(days=1)
        
        # Create output directory
        output_dir = options['output_dir']
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate report
        invoices = Invoice.objects.filter(
            issue_date__range=[start_date, end_date]
        )
        
        # Summary statistics
        stats = invoices.aggregate(
            total_count=Count('id'),
            total_amount=Sum('total_amount'),
            paid_amount=Sum('total_amount', filter=models.Q(status='PAID')),
        )
        
        # Write CSV report
        filename = f"invoice_report_{start_date.strftime('%Y_%m')}.csv"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Summary section
            writer.writerow(['INVOICE REPORT SUMMARY'])
            writer.writerow(['Period', f"{start_date} to {end_date}"])
            writer.writerow(['Total Invoices', stats['total_count']])
            writer.writerow(['Total Amount', f"UGX {stats['total_amount'] or 0:,.2f}"])
            writer.writerow(['Paid Amount', f"UGX {stats['paid_amount'] or 0:,.2f}"])
            writer.writerow([])
            
            # Detailed invoice list
            writer.writerow(['DETAILED INVOICE LIST'])
            writer.writerow([
                'Invoice Number', 'Customer', 'Issue Date', 'Due Date',
                'Amount', 'Status', 'Fiscalized'
            ])
            
            for invoice in invoices:
                writer.writerow([
                    invoice.invoice_number,
                    invoice.sale.customer.name if invoice.sale and invoice.sale.customer else '',
                    invoice.issue_date,
                    invoice.due_date,
                    f"UGX {invoice.total_amount:,.2f}",
                    invoice.get_status_display(),
                    'Yes' if invoice.is_fiscalized else 'No'
                ])
        
        self.stdout.write(
            self.style.SUCCESS(f'Report generated: {filepath}')
        )