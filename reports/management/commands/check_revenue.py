# management/commands/check_revenue.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
from django_tenants.utils import schema_context, get_tenant_model

class Command(BaseCommand):
    help = 'Compare revenue figures across all tenant schemas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            help='Run for a specific schema only (e.g. --schema acme)',
        )

    def handle(self, *args, **options):
        TenantModel = get_tenant_model()
        target_schema = options.get('schema')

        tenants = TenantModel.objects.exclude(schema_name='public')
        if target_schema:
            tenants = tenants.filter(schema_name=target_schema)

        if not tenants.exists():
            self.stdout.write(self.style.WARNING('No tenants found.'))
            return

        today = timezone.now().date()
        thirty_days_ago = today - timedelta(days=30)

        for tenant in tenants:
            self.stdout.write(f'\n── Schema: {tenant.schema_name} ──')

            with schema_context(tenant.schema_name):
                # These imports MUST be inside schema_context
                # so Django resolves them against the right schema
                from stores.models import Store
                from sales.models import Sale
                from company.models import Company

                for company in Company.objects.filter(is_active=True):
                    all_stores  = Store.objects.filter(company=company)
                    store_ids   = all_stores.values_list('id', flat=True)

                    # company_detail logic
                    cd_rev = Sale.objects.filter(
                        store_id__in=store_ids,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID'],
                        created_at__date__gte=thirty_days_ago,
                    ).aggregate(t=Sum('total_amount'))['t'] or 0

                    # tenant_overview logic
                    ov_rev = Sale.objects.filter(
                        store__in=all_stores,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID'],
                        created_at__date__gte=thirty_days_ago,
                    ).aggregate(t=Sum('total_amount'))['t'] or 0

                    match = '✅' if abs(float(cd_rev) - float(ov_rev)) < 0.01 else '❌ MISMATCH'
                    self.stdout.write(
                        f"  {match} {company.name[:28]:<28} "
                        f"cd={float(cd_rev):>14,.0f}  "
                        f"ov={float(ov_rev):>14,.0f}  "
                        f"diff={float(cd_rev)-float(ov_rev):>10,.0f}"
                    )

