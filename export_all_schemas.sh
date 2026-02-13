#!/bin/bash
#
# Export ALL schemas from 'data' database
# 1. Public schema (shared tables)
# 2. Tenant template schema (from 'pada')
#

set -e  # Exit on any error

TENANT_SCHEMA="template"
DB_NAME="data"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Schema Export Script - Database: ${DB_NAME}"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if pg_dump is available
if ! command -v pg_dump &> /dev/null; then
    echo "❌ pg_dump not found. Please install PostgreSQL client tools."
    exit 1
fi

# Check if database exists
echo "🔍 Checking database connection..."
if ! psql -h localhost -U postgres -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
    echo "❌ Database '${DB_NAME}' not found"
    exit 1
fi

echo "✅ Database found"
echo ""

# Export PUBLIC schema
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1/2: Exporting PUBLIC schema..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

pg_dump -h localhost -U postgres -d "${DB_NAME}" \
  --schema=public \
  --schema-only \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  | grep -v "SELECT pg_catalog.setval" \
  > data_public.sql

if [ $? -eq 0 ]; then
    PUBLIC_SIZE=$(du -h data_public.sql | cut -f1)
    PUBLIC_LINES=$(wc -l < data_public.sql)
    echo "✅ Public schema exported: data_public.sql"
    echo "   Size: ${PUBLIC_SIZE} | Lines: ${PUBLIC_LINES}"
else
    echo "❌ Failed to export public schema"
    exit 1
fi

echo ""

# Export TENANT template schema
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2/2: Exporting TENANT template schema (from '${TENANT_SCHEMA}')..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

pg_dump -h localhost -U postgres -d "${DB_NAME}" \
  --schema="${TENANT_SCHEMA}" \
  --schema-only \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  | grep -v "SELECT pg_catalog.setval" \
  | sed "s/CREATE SCHEMA ${TENANT_SCHEMA};/CREATE SCHEMA template;/g" \
  | sed "s/${TENANT_SCHEMA}\./template\./g" \
  | sed "s/SET search_path TO ${TENANT_SCHEMA}/SET search_path TO template/g" \
  > data_tenant.sql

if [ $? -eq 0 ]; then
    TENANT_SIZE=$(du -h data_tenant.sql | cut -f1)
    TENANT_LINES=$(wc -l < data_tenant.sql)
    echo "✅ Tenant template exported: data_tenant.sql"
    echo "   Size: ${TENANT_SIZE} | Lines: ${TENANT_LINES}"
    echo "   Note: '${TENANT_SCHEMA}' → 'template'"
else
    echo "❌ Failed to export tenant schema"
    exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  ✅ Export Complete!"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Generated files:"
echo "  📄 data_public.sql  - Public schema (${PUBLIC_SIZE})"
echo "  📄 data_tenant.sql  - Tenant template (${TENANT_SIZE})"
echo ""
echo "Next steps:"
echo "  1. Copy these files to your Django project"
echo "  2. Use schema_loader.py to load them:"
echo ""
echo "     from schema_loader import load_public_schema, create_tenant_schema"
echo ""
echo "     # Load public schema"
echo "     load_public_schema('data_public.sql')"
echo ""
echo "     # Create new tenant"
echo "     create_tenant_schema('new_tenant', 'data_tenant.sql')"
echo ""