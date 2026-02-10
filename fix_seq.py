#!/usr/bin/env python3
"""
PostgreSQL Sequence Repair Utility (django-tenants aware)

✔ Fixes broken sequences safely
✔ Skips models whose tables do not exist in the schema
✔ Handles public + tenant schemas correctly
✔ Zero false errors

References:
- Django standalone setup:
  https://docs.djangoproject.com/en/stable/topics/settings/#calling-django-setup-is-required-for-standalone-django-usage
- django-tenants schemas:
  https://django-tenants.readthedocs.io/en/latest/
- PostgreSQL to_regclass():
  https://www.postgresql.org/docs/current/functions-info.html
"""

# ============================================================================
# DJANGO BOOTSTRAP (MUST BE FIRST)
# ============================================================================

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tenancy.settings")
django.setup()

# ============================================================================
# IMPORTS
# ============================================================================

import logging
from django.apps import apps
from django.db import connection
from django_tenants.utils import schema_context, get_tenant_model

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sequence_fixer")

# ============================================================================
# HELPERS
# ============================================================================

def table_exists(schema, table):
    """
    Check if a table exists in a given schema (PostgreSQL-safe)
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass(%s)",
            [f"{schema}.{table}"]
        )
        return cursor.fetchone()[0] is not None


# ============================================================================
# CORE SEQUENCE FIXER
# ============================================================================

def fix_sequence_for_model(model, schema):
    table = model._meta.db_table
    pk = model._meta.pk

    # Only integer PKs have sequences
    if pk.get_internal_type() not in ("AutoField", "BigAutoField"):
        return False

    # Skip if table does not exist in this schema
    if not table_exists(schema, table):
        return False

    try:
        with connection.cursor() as cursor:
            # Get sequence
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                [f"{schema}.{table}", pk.column]
            )
            seq = cursor.fetchone()[0]

            if not seq:
                return False

            # Get max ID
            cursor.execute(
                f"SELECT COALESCE(MAX({pk.column}), 0) FROM {schema}.{table}"
            )
            max_id = cursor.fetchone()[0]

            # Reset sequence
            cursor.execute(
                "SELECT setval(%s, %s, false)",
                [seq, max_id + 1]
            )

            logger.info(f"  ✔ {schema}.{table} → {seq} set to {max_id + 1}")
            return True

    except Exception as e:
        logger.error(f"  ✖ {schema}.{table} ERROR: {e}")
        return False


# ============================================================================
# SCHEMA FIXER
# ============================================================================

def fix_all_sequences_in_schema(schema):
    logger.info("\n" + "=" * 75)
    logger.info(f"FIXING SCHEMA: {schema}")
    logger.info("=" * 75)

    fixed = 0
    skipped = 0

    for model in apps.get_models():
        if fix_sequence_for_model(model, schema):
            fixed += 1
        else:
            skipped += 1

    logger.info("-" * 75)
    logger.info(f"RESULT → Fixed: {fixed} | Skipped: {skipped}")
    logger.info("=" * 75)

    return fixed, skipped


# ============================================================================
# TENANT FIXER
# ============================================================================

def fix_all_tenant_sequences():
    Tenant = get_tenant_model()
    tenants = Tenant.objects.all()

    logger.info(f"\nFound {tenants.count()} tenant(s)")

    total_fixed = 0
    total_skipped = 0

    for tenant in tenants:
        logger.info(f"\nTenant: {tenant.schema_name}")
        with schema_context(tenant.schema_name):
            f, s = fix_all_sequences_in_schema(tenant.schema_name)
            total_fixed += f
            total_skipped += s

    logger.info("\n" + "=" * 75)
    logger.info("ALL TENANTS COMPLETE")
    logger.info(f"TOTAL FIXED: {total_fixed}")
    logger.info(f"TOTAL SKIPPED: {total_skipped}")
    logger.info("=" * 75)


# ============================================================================
# QUICK FIX
# ============================================================================

def quick_fix_current_schema():
    schema = connection.schema_name
    logger.info(f"\nQuick-fix schema: {schema}")
    fix_all_sequences_in_schema(schema)


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":

    print("\n" + "=" * 75)
    print("POSTGRESQL SEQUENCE FIXER (django-tenants)")
    print("=" * 75)
    print("1) Fix ALL tenant schemas")
    print("2) Fix ONE schema")
    print("3) Fix PUBLIC schema")
    print("4) Fix CURRENT schema")
    print("=" * 75)

    choice = input("Select option (1-4): ").strip()

    if choice == "1":
        fix_all_tenant_sequences()
    elif choice == "2":
        schema = input("Enter schema name: ").strip()
        fix_all_sequences_in_schema(schema)
    elif choice == "3":
        fix_all_sequences_in_schema("public")
    elif choice == "4":
        quick_fix_current_schema()
    else:
        print("Invalid option")

    print("\n✅ DONE\n")
