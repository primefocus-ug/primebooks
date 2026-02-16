# Run this in Django shell: python manage.py shell

from django.db import connection
from django_tenants.utils import schema_context

def fix_now(schema='rem'):
    with schema_context(schema):
        with connection.cursor() as c:
            c.execute(f"""
                DO $$
                DECLARE r RECORD; max_id INTEGER;
                BEGIN
                    FOR r IN SELECT sequencename, REPLACE(sequencename, '_id_seq', '') as tablename 
                             FROM pg_sequences WHERE schemaname = '{schema}'
                    LOOP
                        EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM {schema}.%I', r.tablename) INTO max_id;
                        EXECUTE format('SELECT setval(%L, GREATEST(%s, 1), true)', '{schema}.' || r.sequencename, max_id);
                        RAISE NOTICE 'Fixed %: max=%, next=%', r.tablename, max_id, max_id + 1;
                    END LOOP;
                END $$;
            """)
    print(f"✅ Fixed all sequences in schema '{schema}'")

# Fix your schema
fix_now('rem')  # Change 'rem' to your schema name if different