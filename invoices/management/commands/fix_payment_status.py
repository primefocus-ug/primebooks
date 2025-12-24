from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django_tenants.utils import tenant_context, get_tenant_model
from django.utils import timezone
from decimal import Decimal
import logging
from datetime import date

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix payment statuses for all invoices across all tenants'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            help='Specific tenant schema name to fix (optional)'
        )

    def handle(self, *args, **options):
        TenantModel = get_tenant_model()

        # Get tenants to process
        if options['tenant']:
            tenants = TenantModel.objects.filter(schema_name=options['tenant'])
        else:
            tenants = TenantModel.objects.all()

        total_fixed = 0

        for tenant in tenants:
            if tenant.schema_name == 'public':
                continue  # Skip public schema

            self.stdout.write(f"\n📋 Processing tenant: {tenant.name} ({tenant.schema_name})")

            with tenant_context(tenant):
                try:
                    # Import inside tenant context
                    from invoices.models import Invoice
                    from sales.models import Sale

                    invoices = Invoice.objects.all().select_related('sale')
                    tenant_fixed = 0

                    for invoice in invoices:
                        try:
                            with transaction.atomic():
                                sale = invoice.sale
                                old_status = sale.payment_status

                                # Calculate total paid manually
                                total_paid = invoice.payments.aggregate(
                                    total=Sum('amount')
                                )['total'] or Decimal('0')

                                total_amount = invoice.total_amount or Decimal('0')

                                # Determine new status
                                if total_paid >= total_amount:
                                    new_payment_status = 'PAID'
                                    new_status = 'COMPLETED'
                                elif total_paid > 0:
                                    new_payment_status = 'PARTIALLY_PAID'
                                    new_status = 'PENDING_PAYMENT'
                                else:
                                    new_payment_status = 'PENDING'
                                    new_status = 'PENDING_PAYMENT'

                                # Check if overdue
                                if sale.due_date and sale.due_date < date.today():
                                    if new_payment_status in ['PENDING', 'PARTIALLY_PAID']:
                                        new_payment_status = 'OVERDUE'

                                # Update if changed
                                if new_payment_status != old_status:
                                    sale.payment_status = new_payment_status
                                    sale.status = new_status
                                    sale.save(update_fields=['payment_status', 'status', 'updated_at'])
                                    tenant_fixed += 1

                                    logger.info(
                                        f"Fixed invoice {invoice.id} in tenant {tenant.schema_name}: "
                                        f"{old_status} -> {new_payment_status}"
                                    )

                        except Exception as e:
                            logger.error(
                                f"Error fixing invoice {invoice.id} in tenant {tenant.schema_name}: {e}"
                            )

                    total_fixed += tenant_fixed
                    self.stdout.write(
                        f"  ✅ Fixed {tenant_fixed} invoice(s) in tenant {tenant.name}"
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  ❌ Error processing tenant {tenant.name}: {e}")
                    )

        self.stdout.write(
            self.style.SUCCESS(f'\n✨ Successfully fixed {total_fixed} invoice payment statuses across all tenants')
        )