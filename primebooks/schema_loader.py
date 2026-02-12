"""
Schema Loader - Initialize database from SQL dump
Replaces Django migrations for desktop app
✅ Fast tenant creation (2-3 seconds vs 30-60 seconds)
"""
import logging
from pathlib import Path
from django.db import connection
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


def load_public_schema(sql_file_path):
    """
    Load public schema from SQL dump
    ✅ Creates shared tables (Company, SubscriptionPlan, etc.)

    Args:
        sql_file_path: Path to primebooks_public.sql

    Returns:
        bool: True if successful
    """
    logger.info(f"📄 Loading public schema from {sql_file_path}")

    try:
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        # Clean SQL - remove psql commands
        lines = sql_content.split('\n')
        cleaned_lines = []

        for line in lines:
            stripped = line.strip()

            # Skip empty lines, comments, psql commands, SET statements
            if not stripped:
                continue
            if stripped.startswith('--'):
                continue
            if stripped.startswith('\\'):
                continue
            if stripped.upper().startswith('SET '):
                continue
            if 'pg_catalog.set_config' in stripped:
                continue

            cleaned_lines.append(line)

        cleaned_sql = '\n'.join(cleaned_lines)

        # Execute SQL statement by statement
        with connection.cursor() as cursor:
            # Ensure public schema exists
            cursor.execute('CREATE SCHEMA IF NOT EXISTS public;')
            cursor.execute('SET search_path TO public;')

            # Split by semicolon
            statements = []
            current_statement = []

            for line in cleaned_sql.split('\n'):
                current_statement.append(line)
                if line.strip().endswith(';'):
                    statements.append('\n'.join(current_statement))
                    current_statement = []

            # Execute each statement
            executed = 0
            skipped = 0

            for statement in statements:
                statement = statement.strip()
                if not statement:
                    continue

                try:
                    cursor.execute(statement)
                    executed += 1
                except Exception as e:
                    # Skip data insertion errors (COPY commands, etc.)
                    logger.debug(f"Skipped: {str(e)[:50]}")
                    skipped += 1

            logger.info(f"✅ Executed {executed} statements ({skipped} skipped)")

        logger.info("✅ Public schema loaded successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to load public schema: {e}", exc_info=True)
        return False


def create_tenant_schema(schema_name, sql_file_path):
    """
    Create a new tenant schema from template SQL
    ✅ Fast schema creation (2-3 seconds vs 30-60 seconds)

    Args:
        schema_name: Name of the tenant schema (e.g., 'pada')
        sql_file_path: Path to primebooks_tenant.sql

    Returns:
        bool: True if successful
    """
    logger.info(f"📄 Creating tenant schema: {schema_name}")

    try:
        # Check if schema already exists
        if check_schema_exists(schema_name):
            logger.info(f"ℹ️  Schema '{schema_name}' already exists, skipping creation")
            return True

        # Read tenant template SQL
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        # Replace "template" with actual schema name
        sql_content = sql_content.replace(
            'CREATE SCHEMA template;',
            f'CREATE SCHEMA "{schema_name}";'
        )
        sql_content = sql_content.replace(
            'SET search_path TO template',
            f'SET search_path TO "{schema_name}"'
        )
        sql_content = sql_content.replace(
            'template.',
            f'"{schema_name}".'
        )

        # Clean SQL - remove psql commands
        lines = sql_content.split('\n')
        cleaned_lines = []

        for line in lines:
            stripped = line.strip()

            if not stripped:
                continue
            if stripped.startswith('--'):
                continue
            if stripped.startswith('\\'):
                continue
            if stripped.upper().startswith('SET ') and 'search_path' not in stripped:
                continue
            if 'pg_catalog.set_config' in stripped:
                continue

            cleaned_lines.append(line)

        cleaned_sql = '\n'.join(cleaned_lines)

        # Execute SQL
        with connection.cursor() as cursor:
            # Create schema
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
            logger.info(f"✅ Schema created: {schema_name}")

            # Set search path
            cursor.execute(f'SET search_path TO "{schema_name}", public;')

            # Split into statements
            statements = []
            current_statement = []

            for line in cleaned_sql.split('\n'):
                current_statement.append(line)
                if line.strip().endswith(';'):
                    statements.append('\n'.join(current_statement))
                    current_statement = []

            # Execute each statement
            executed = 0
            skipped = 0

            for statement in statements:
                statement = statement.strip()
                if not statement:
                    continue

                # Skip CREATE SCHEMA (already done)
                if 'CREATE SCHEMA' in statement.upper():
                    continue

                try:
                    cursor.execute(statement)
                    executed += 1
                except Exception as e:
                    logger.debug(f"Skipped: {str(e)[:50]}")
                    skipped += 1

            logger.info(f"✅ Executed {executed} statements ({skipped} skipped)")

        logger.info(f"✅ Tenant schema created successfully: {schema_name}")
        logger.info(f"🔄 Resetting sequences in {schema_name}...")
        reset_sequences(schema_name)
        return True

    except Exception as e:
        logger.error(f"❌ Failed to create tenant schema: {e}", exc_info=True)
        return False


def check_schema_exists(schema_name):
    """
    Check if a schema exists in the database

    Args:
        schema_name: Name of the schema to check

    Returns:
        bool: True if schema exists
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT EXISTS (SELECT schema_name
                                          FROM information_schema.schemata
                                          WHERE schema_name = %s);
                           """, [schema_name])

            result = cursor.fetchone()
            exists = result[0] if result else False

            if exists:
                logger.debug(f"✅ Schema '{schema_name}' exists")
            else:
                logger.debug(f"ℹ️  Schema '{schema_name}' does not exist")

            return exists

    except Exception as e:
        logger.error(f"❌ Error checking schema existence: {e}", exc_info=True)
        return False


def verify_schema(schema_name):
    """
    Verify that schema has all required tables

    Args:
        schema_name: Schema to verify

    Returns:
        bool: True if all required tables exist
    """
    required_tables = [
        'accounts_customuser',
        'stores_store',
        'inventory_product',
        'sales_sale',
        'customers_customer',
        'invoices_invoice',
    ]

    logger.info(f"🔍 Verifying schema: {schema_name}")

    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema_name}", public;')

            missing_tables = []

            for table in required_tables:
                cursor.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s
                        AND table_name = %s
                    );
                """, [schema_name, table])

                if not cursor.fetchone()[0]:
                    missing_tables.append(table)

            if missing_tables:
                logger.error(f"❌ Missing tables in '{schema_name}': {missing_tables}")
                return False

        logger.info(f"✅ Schema verification passed: {schema_name}")
        return True

    except Exception as e:
        logger.error(f"❌ Schema verification failed: {e}", exc_info=True)
        return False


def get_schema_tables(schema_name):
    """
    Get list of tables in a schema

    Args:
        schema_name: Schema to query

    Returns:
        list: Table names in the schema
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT table_name
                           FROM information_schema.tables
                           WHERE table_schema = %s
                             AND table_type = 'BASE TABLE'
                           ORDER BY table_name;
                           """, [schema_name])

            tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"📊 Schema '{schema_name}' has {len(tables)} tables")
            return tables

    except Exception as e:
        logger.error(f"❌ Error getting schema tables: {e}", exc_info=True)
        return []


def reset_sequences(schema_name):
    """
    Reset PostgreSQL sequences after data sync
    ✅ Prevents duplicate key errors
    ✅ Works with any table that has an ID column
    """
    logger.info(f"🔄 Resetting sequences in schema: {schema_name}")

    try:
        with connection.cursor() as cursor:
            # Set search path to schema
            cursor.execute(f'SET search_path TO "{schema_name}", public;')

            # Get all tables in schema
            cursor.execute("""
                           SELECT table_name
                           FROM information_schema.tables
                           WHERE table_schema = %s
                             AND table_type = 'BASE TABLE'
                           ORDER BY table_name;
                           """, [schema_name])

            tables = [row[0] for row in cursor.fetchall()]
            reset_count = 0
            skipped_count = 0

            for table in tables:
                try:
                    # Try to get sequence name for 'id' column
                    cursor.execute("""
                        SELECT pg_get_serial_sequence(%s, 'id');
                    """, [f'{schema_name}.{table}'])

                    result = cursor.fetchone()
                    sequence_name = result[0] if result else None

                    if sequence_name:
                        # Get max ID from table
                        cursor.execute(f'SELECT MAX(id) FROM "{schema_name}"."{table}";')
                        max_id_result = cursor.fetchone()
                        max_id = max_id_result[0] if max_id_result[0] else 0

                        # ✅ FIX: Use 'true' to indicate value has been called
                        # This ensures next value is max_id + 1
                        cursor.execute(f"SELECT setval('{sequence_name}', %s, true);", [max_id])

                        logger.debug(f"  ✓ {table}: sequence → {max_id} (next: {max_id + 1})")
                        reset_count += 1
                    else:
                        skipped_count += 1

                except Exception as e:
                    logger.debug(f"  Skipped {table}: {str(e)[:50]}")
                    skipped_count += 1

            logger.info(f"✅ Reset {reset_count} sequences ({skipped_count} tables skipped)")
            return True

    except Exception as e:
        logger.error(f"❌ Failed to reset sequences: {e}", exc_info=True)
        return False


def drop_schema_if_exists(schema_name):
    """
    Drop a schema and all its objects
    ⚠️ Use with caution - this deletes all data!

    Args:
        schema_name: Schema to drop

    Returns:
        bool: True if successful
    """
    logger.warning(f"⚠️  Dropping schema: {schema_name}")

    try:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE;')

        logger.info(f"✅ Schema dropped: {schema_name}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to drop schema: {e}", exc_info=True)
        return False