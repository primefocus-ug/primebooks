from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.utils import get_tenant_model, schema_context


class Command(BaseCommand):
    help = 'Install PostgreSQL triggers to auto-fix sequences on insert'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("""
                           CREATE
                           OR REPLACE FUNCTION auto_fix_sequence()
                RETURNS TRIGGER AS $$
                DECLARE
                           seq_name TEXT;
                    max_id
                           BIGINT;
                           BEGIN
                    seq_name
                           := pg_get_serial_sequence(TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, 'id');

                    IF
                           seq_name IS NOT NULL THEN
                        EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I.%I', 
                                      TG_TABLE_SCHEMA, TG_TABLE_NAME) INTO max_id;
                           EXECUTE format('SELECT setval(%L, GREATEST(%s, 1), true)',
                                          seq_name, max_id);
                           END IF;

                           RETURN NEW;
                           END;
                $$
                           LANGUAGE plpgsql;
                           """)
            self.stdout.write(self.style.SUCCESS('✓ Created trigger function'))

        TenantModel = get_tenant_model()
        tables = ['sales_sale', 'sales_saleitem', 'sales_receipt',
                  'inventory_stockmovement', 'invoices_invoice']

        for tenant in TenantModel.objects.all():
            with schema_context(tenant.schema_name):
                with connection.cursor() as cursor:
                    for table in tables:
                        try:
                            cursor.execute(f"DROP TRIGGER IF EXISTS {table}_auto_seq ON {table};")
                            cursor.execute(f"""
                                CREATE TRIGGER {table}_auto_seq
                                AFTER INSERT ON {table}
                                FOR EACH STATEMENT
                                EXECUTE FUNCTION auto_fix_sequence();
                            """)
                            self.stdout.write(self.style.SUCCESS(f'✓ {tenant.schema_name}.{table}'))
                        except Exception as e:
                            self.stdout.write(self.style.WARNING(f'✗ {tenant.schema_name}.{table}: {e}'))

        self.stdout.write(self.style.SUCCESS('\n✅ Triggers installed'))