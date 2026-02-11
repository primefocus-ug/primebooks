#!/bin/bash
# quick_fix.sh - Emergency fix for sequence issues
# Usage: bash quick_fix.sh

echo "========================================================================"
echo "EMERGENCY DATABASE FIX"
echo "========================================================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get database credentials
echo -e "${YELLOW}Enter your PostgreSQL credentials:${NC}"
read -p "Database name [data]: " DB_NAME
DB_NAME=${DB_NAME:-data}

read -p "Database user [postgres]: " DB_USER
DB_USER=${DB_USER:-postgres}

read -p "Database host [localhost]: " DB_HOST
DB_HOST=${DB_HOST:-localhost}

echo ""
echo -e "${GREEN}Connecting to database: $DB_NAME@$DB_HOST${NC}"
echo ""

# Run the fix
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" << 'EOF'
-- Quick sequence fix for all schemas
DO $$
DECLARE
    schema_rec RECORD;
    table_rec RECORD;
    max_id BIGINT;
    new_val BIGINT;
    fixed_count INT := 0;
BEGIN
    RAISE NOTICE '=== FIXING ALL SEQUENCES ===';
    RAISE NOTICE '';

    -- Loop through all non-system schemas
    FOR schema_rec IN
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        AND schema_name NOT LIKE 'pg_%'
    LOOP
        -- Loop through tables with sequences
        FOR table_rec IN
            SELECT
                tablename,
                pg_get_serial_sequence(schema_rec.schema_name || '.' || tablename, 'id') as seq
            FROM pg_tables
            WHERE schemaname = schema_rec.schema_name
            AND pg_get_serial_sequence(schema_rec.schema_name || '.' || tablename, 'id') IS NOT NULL
        LOOP
            BEGIN
                -- Get max ID
                EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I.%I',
                    schema_rec.schema_name, table_rec.tablename)
                INTO max_id;

                new_val := max_id + 1;

                -- Fix sequence
                EXECUTE format('SELECT setval(%L, %s, false)', table_rec.seq, new_val);

                RAISE NOTICE '✓ %.%: % → %',
                    schema_rec.schema_name, table_rec.tablename,
                    table_rec.seq, new_val;

                fixed_count := fixed_count + 1;
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE '⚠ Skipped %.%: %',
                    schema_rec.schema_name, table_rec.tablename, SQLERRM;
            END;
        END LOOP;
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE '==============================================';
    RAISE NOTICE '✓ FIXED % SEQUENCES', fixed_count;
    RAISE NOTICE '==============================================';
END $$;
EOF

echo ""
echo -e "${GREEN}========================================================================"
echo "✓ SEQUENCES FIXED!"
echo "========================================================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Restart your Django server (Ctrl+C, then 'python manage.py runserver')"
echo "  2. Try creating a sale again"
echo ""