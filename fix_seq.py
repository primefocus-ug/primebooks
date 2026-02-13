# test_schema.py
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')
django.setup()

from primebooks.schema_loader import create_tenant_schema, verify_schema, get_schema_tables
from pathlib import Path

# Path to your SQL dump
sql_file = Path('/home/prime-focus/current/off/primebooks/primebooks_tenant.sql')

print(f"SQL file: {sql_file}")
print(f"Exists: {sql_file.exists()}\n")

# Test creating a schema
test_schema = 'test_fast_123'

print(f"Creating schema '{test_schema}'...")
success = create_tenant_schema(test_schema, sql_file)

if success:
    print("\n✅ Schema created!\n")

    # Verify
    print("Verifying schema...")
    verify_schema(test_schema)

    # List tables
    print("\nTables in schema:")
    tables = get_schema_tables(test_schema)
    for t in tables[:10]:  # Show first 10
        print(f"  • {t}")
    print(f"  ... ({len(tables)} total)")

    print("\n✅ All tests passed!")
else:
    print("\n❌ Schema creation failed!")

