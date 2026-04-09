from django.db import connection
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
            print(f"Orphaned tenant: {tenant.schema_name} (pk={pk_value}) — cleaning up...")

            cursor.execute("""
                SELECT kcu.table_name, kcu.column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints AS rc
                    ON tc.constraint_name = rc.constraint_name
                    AND tc.table_schema = rc.constraint_schema
                JOIN information_schema.key_column_usage AS ccu
                    ON ccu.constraint_name = rc.unique_constraint_name
                    AND ccu.table_schema = rc.unique_constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND ccu.table_name = %s
                  AND ccu.table_schema = 'public'
            """, [db_table])

            fk_refs = cursor.fetchall()

            for ref_table, ref_column in fk_refs:
                print(f"  Deleting from {ref_table} where {ref_column} = {pk_value}")
                cursor.execute(
                    f'DELETE FROM "{ref_table}" WHERE "{ref_column}" = %s',
                    [pk_value]
                )

            cursor.execute(
                f'DELETE FROM "{db_table}" WHERE "{pk_column}" = %s',
                [pk_value]
            )
            print(f"  Deleted company row {pk_value} ✓")

print("Done.")