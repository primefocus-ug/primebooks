import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')
django.setup()

from django.db import connection, transaction
from company.models import Company

db_table  = Company._meta.db_table
pk_column = Company._meta.pk.column

print("Scanning for orphaned tenants...")

for tenant in Company.objects.exclude(schema_name='public'):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
            [tenant.schema_name]
        )
        exists = cursor.fetchone()

        if not exists:
            pk_value = tenant.pk
            print(f"\nOrphaned tenant: {tenant.schema_name} (pk={pk_value}) — cleaning up...")

            try:
                with transaction.atomic():
                    # Reliable FK discovery via pg_constraint
                    cursor.execute("""
                        SELECT
                            child_class.relname AS table_name,
                            child_attr.attname AS column_name
                        FROM pg_constraint con
                        JOIN pg_class parent_class ON con.confrelid = parent_class.oid
                        JOIN pg_namespace parent_ns ON parent_class.relnamespace = parent_ns.oid
                        JOIN pg_class child_class ON con.conrelid = child_class.oid
                        JOIN pg_namespace child_ns ON child_class.relnamespace = child_ns.oid
                        JOIN pg_attribute child_attr
                            ON child_attr.attrelid = child_class.oid
                            AND child_attr.attnum = ANY(con.conkey)
                        WHERE con.contype = 'f'
                          AND parent_ns.nspname = 'public'
                          AND parent_class.relname = %s
                          AND child_ns.nspname = 'public'
                    """, [db_table])

                    fk_refs = cursor.fetchall()
                    print(f"  Found {len(fk_refs)} FK reference(s):")

                    for ref_table, ref_column in fk_refs:
                        print(f"    → Deleting from \"{ref_table}\" where \"{ref_column}\" = {pk_value}")
                        cursor.execute(
                            f'DELETE FROM public."{ref_table}" WHERE "{ref_column}" = %s',
                            [pk_value]
                        )
                        print(f"      ✓ Done")

                    # Now safe to delete the company row
                    cursor.execute(
                        f'DELETE FROM public."{db_table}" WHERE "{pk_column}" = %s',
                        [pk_value]
                    )
                    print(f"  ✓ Deleted company row {pk_value}")

            except Exception as e:
                print(f"  ✗ Failed to delete tenant: {e}")

print("\nDone.")