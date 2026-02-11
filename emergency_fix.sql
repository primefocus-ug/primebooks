-- EMERGENCY_FIX.sql
-- Run this directly in PostgreSQL to fix sequences immediately
-- Usage: psql -U postgres -d your_database_name -f EMERGENCY_FIX.sql

\echo '=========================================================================='
\echo 'EMERGENCY SEQUENCE FIX'
\echo '=========================================================================='

-- Kill broken connections (optional, if you're not connected to the DB)
-- SELECT pg_terminate_backend(pg_stat_activity.pid)
-- FROM pg_stat_activity
-- WHERE pg_stat_activity.datname = current_database()
-- AND pid <> pg_backend_pid();

\echo ''
\echo 'Fixing sequences in PUBLIC schema...'
\echo ''

-- Fix sequences in public schema (if any)
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT
            schemaname,
            tablename,
            pg_get_serial_sequence(schemaname || '.' || tablename, 'id') as seq
        FROM pg_tables
        WHERE schemaname = 'public'
        AND pg_get_serial_sequence(schemaname || '.' || tablename, 'id') IS NOT NULL
    LOOP
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I.%I), 0) + 1, false)',
            r.seq,
            r.schemaname,
            r.tablename
        );
        RAISE NOTICE 'Fixed sequence for %.%', r.schemaname, r.tablename;
    END LOOP;
END $$;

\echo ''
\echo 'Fixing sequences in ALL TENANT schemas...'
\echo ''

-- Fix sequences in all tenant schemas
DO $$
DECLARE
    schema_rec RECORD;
    table_rec RECORD;
    max_id BIGINT;
    new_val BIGINT;
BEGIN
    -- Loop through all schemas (except system schemas)
    FOR schema_rec IN
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        AND schema_name NOT LIKE 'pg_%'
    LOOP
        RAISE NOTICE '';
        RAISE NOTICE '=== Processing schema: % ===', schema_rec.schema_name;

        -- Loop through tables in this schema that have sequences
        FOR table_rec IN
            SELECT
                tablename,
                pg_get_serial_sequence(schema_rec.schema_name || '.' || tablename, 'id') as seq
            FROM pg_tables
            WHERE schemaname = schema_rec.schema_name
            AND pg_get_serial_sequence(schema_rec.schema_name || '.' || tablename, 'id') IS NOT NULL
        LOOP
            -- Get max ID
            EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I.%I',
                schema_rec.schema_name, table_rec.tablename)
            INTO max_id;

            new_val := max_id + 1;

            -- Fix sequence
            EXECUTE format('SELECT setval(%L, %s, false)', table_rec.seq, new_val);

            RAISE NOTICE '  ✓ Fixed %.%: sequence → %',
                schema_rec.schema_name, table_rec.tablename, new_val;
        END LOOP;
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE '========================================================================';
    RAISE NOTICE '✓ ALL SEQUENCES FIXED!';
    RAISE NOTICE '========================================================================';
END $$;

\echo ''
\echo 'Done! Please restart your Django server.'
\echo ''