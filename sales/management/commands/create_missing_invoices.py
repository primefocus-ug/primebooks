from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import tenant_context, get_tenant_model
from sales.models import Sale
from invoices.models import Invoice
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create missing Invoice records for Sales with document_type=INVOICE (Multi-tenant)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            help='Specific tenant schema name (optional, runs for all if not specified)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        specific_tenant = options.get('tenant')

        TenantModel = get_tenant_model()

        # Get tenants to process
        if specific_tenant:
            tenants = TenantModel.objects.filter(schema_name=specific_tenant)
            if not tenants.exists():
                self.stdout.write(
                    self.style.ERROR(f"Tenant '{specific_tenant}' not found!")
                )
                return
        else:
            # Exclude public schema
            tenants = TenantModel.objects.exclude(schema_name='public')

        total_tenants = tenants.count()
        self.stdout.write(
            self.style.SUCCESS(f"Processing {total_tenants} tenant(s)...")
        )

        overall_created = 0
        overall_failed = 0

        for tenant in tenants:
            self.stdout.write(
                self.style.WARNING(f"\n{'=' * 60}")
            )
            self.stdout.write(
                self.style.WARNING(f"Processing Tenant: {tenant.schema_name} - {tenant.name}")
            )
            self.stdout.write(
                self.style.WARNING(f"{'=' * 60}")
            )

            try:
                with tenant_context(tenant):
                    created, failed = self.process_tenant(tenant, dry_run)
                    overall_created += created
                    overall_failed += failed
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error processing tenant {tenant.schema_name}: {e}")
                )
                logger.error(f"Error processing tenant {tenant.schema_name}: {e}", exc_info=True)

        # Summary
        self.stdout.write(
            self.style.SUCCESS(f"\n{'=' * 60}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"SUMMARY")
        )
        self.stdout.write(
            self.style.SUCCESS(f"{'=' * 60}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"✅ Total created: {overall_created}")
        )
        if overall_failed > 0:
            self.stdout.write(
                self.style.ERROR(f"❌ Total failed: {overall_failed}")
            )

    def process_tenant(self, tenant, dry_run):
        """Process a single tenant"""
        # Find sales that are invoices but don't have Invoice records
        invoice_sales = Sale.objects.filter(document_type='INVOICE')

        total_sales = invoice_sales.count()
        self.stdout.write(f"Found {total_sales} sales with document_type='INVOICE'")

        if total_sales == 0:
            self.stdout.write(
                self.style.WARNING("  No invoice sales found for this tenant")
            )
            return 0, 0

        # Find which ones are missing Invoice records
        missing_invoices = []
        existing_invoices = []

        for sale in invoice_sales:
            try:
                if hasattr(sale, 'invoice_detail') and sale.invoice_detail is not None:
                    existing_invoices.append(sale)
                else:
                    missing_invoices.append(sale)
            except Invoice.DoesNotExist:
                missing_invoices.append(sale)

        self.stdout.write(
            self.style.SUCCESS(f"  ✓ Already have invoices: {len(existing_invoices)}")
        )
        self.stdout.write(
            self.style.WARNING(f"  ⚠ Missing Invoice records: {len(missing_invoices)}")
        )

        if len(missing_invoices) == 0:
            self.stdout.write(
                self.style.SUCCESS("  All invoices already exist!")
            )
            return 0, 0

        if dry_run:
            self.stdout.write(
                self.style.WARNING("  DRY RUN - No changes will be made")
            )
            for sale in missing_invoices[:5]:  # Show first 5
                self.stdout.write(f"    Would create Invoice for: {sale.document_number}")
            if len(missing_invoices) > 5:
                self.stdout.write(f"    ... and {len(missing_invoices) - 5} more")
            return 0, 0

        # Create missing Invoice records
        created_count = 0
        failed_count = 0

        for sale in missing_invoices:
            try:
                with transaction.atomic():
                    # Determine business type
                    business_type = 'B2C'
                    if sale.customer:
                        if hasattr(sale.customer, 'customer_type') and sale.customer.customer_type:
                            if sale.customer.customer_type.upper() == 'BUSINESS':
                                business_type = 'B2B'
                            elif sale.customer.customer_type.upper() in ['GOVERNMENT', 'PUBLIC']:
                                business_type = 'B2G'
                        elif hasattr(sale.customer, 'tin') and sale.customer.tin:
                            business_type = 'B2B'

                    # Create Invoice
                    invoice = Invoice.objects.create(
                        sale=sale,
                        store=sale.store,
                        terms='',
                        purchase_order='',
                        created_by=sale.created_by,
                        business_type=business_type,
                        operator_name=sale.created_by.get_full_name() if sale.created_by else 'System',
                        fiscalization_status='pending',
                        efris_document_type='1',  # Normal Invoice
                        auto_fiscalize=False  # Don't auto-fiscalize old invoices
                    )

                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"    ✓ Created Invoice #{invoice.id} for {sale.document_number}")
                    )

            except Exception as e:
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(f"    ✗ Failed for {sale.document_number}: {e}")
                )
                logger.error(f"Failed to create invoice for sale {sale.id}: {e}", exc_info=True)

        self.stdout.write(
            self.style.SUCCESS(f"  ✅ Created {created_count} Invoice records")
        )

        if failed_count > 0:
            self.stdout.write(
                self.style.ERROR(f"  ❌ Failed {failed_count} Invoice records")
            )

        return created_count, failed_count