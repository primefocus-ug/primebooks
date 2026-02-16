#!/usr/bin/env python3
"""
Generate SQL dumps for desktop app
Creates data_public.sql and data_tenant.sql
"""
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run shell command and handle errors"""
    print(f"\n📝 {description}...")
    print(f"   Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"   ✅ Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Failed: {e.stderr}")
        return False


def main():
    print("=" * 70)
    print("🗄️  SQL DUMP GENERATOR FOR PRIMEBOOKS DESKTOP")
    print("=" * 70)

    # ✅ YOUR SPECIFIC SETUP
    db_host = "localhost"
    db_port = "5432"
    db_name = "data"  # ✅ Your database name
    db_user = "postgres"
    tenant_schema = "template"  # ✅ Your complete schema

    print(f"\n📋 Configuration:")
    print(f"   Database: {db_name}")
    print(f"   Host: {db_host}:{db_port}")
    print(f"   User: {db_user}")
    print(f"   Template schema: {tenant_schema}")

    print("\n" + "=" * 70)
    print("STEP 1: Creating data_public.sql")
    print("=" * 70)

    # Create public schema dump
    public_cmd = [
        'pg_dump',
        '-h', db_host,
        '-p', db_port,
        '-U', db_user,
        '-d', db_name,
        '--schema=public',
        '--schema-only',
        '--no-owner',
        '--no-privileges',
        '--clean',
        '--if-exists',
    ]

    print(f"   Running: pg_dump ... > data_public.sql")

    with open('data_public.sql', 'w') as f:
        result = subprocess.run(public_cmd, stdout=f, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        size = Path('data_public.sql').stat().st_size / 1024
        print(f"   ✅ Created data_public.sql ({size:.1f} KB)")
    else:
        print(f"   ❌ Failed: {result.stderr}")
        return False

    print("\n" + "=" * 70)
    print("STEP 2: Creating data_tenant.sql")
    print("=" * 70)

    # Create tenant schema dump
    tenant_cmd = [
        'pg_dump',
        '-h', db_host,
        '-p', db_port,
        '-U', db_user,
        '-d', db_name,
        f'--schema={tenant_schema}',
        '--schema-only',
        '--no-owner',
        '--no-privileges',
        '--clean',
        '--if-exists',
    ]

    print(f"   Running: pg_dump --schema={tenant_schema} ... > data_tenant.sql")

    with open('data_tenant.sql', 'w') as f:
        result = subprocess.run(tenant_cmd, stdout=f, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        size = Path('data_tenant.sql').stat().st_size / 1024
        print(f"   ✅ Created data_tenant.sql ({size:.1f} KB)")
    else:
        print(f"   ❌ Failed: {result.stderr}")
        return False

    print("\n" + "=" * 70)
    print("STEP 3: Verifying tenant dump (schema already named 'template')")
    print("=" * 70)

    # Since your schema is already called 'template', no replacement needed!
    sql_file = Path('data_tenant.sql')
    content = sql_file.read_text()

    # Count template occurrences
    template_count = content.count('template.')
    create_schema_count = content.count('CREATE SCHEMA template;')

    print(f"   ✅ Found {template_count} references to 'template.'")
    print(f"   ✅ Found {create_schema_count} CREATE SCHEMA statement")

    # Verify structure
    if 'CREATE TABLE template.' in content:
        print(f"   ✅ Contains CREATE TABLE statements")
    else:
        print(f"   ⚠️  No CREATE TABLE statements found - dump may be empty!")

    print("\n" + "=" * 70)
    print("✅ SQL DUMPS CREATED SUCCESSFULLY!")
    print("=" * 70)

    print("\n📄 Files created:")
    print(f"   • data_public.sql ({Path('data_public.sql').stat().st_size / 1024:.1f} KB)")
    print(f"   • data_tenant.sql ({Path('data_tenant.sql').stat().st_size / 1024:.1f} KB)")

    # Show table counts
    print("\n📊 Table counts:")
    with open('data_public.sql') as f:
        public_tables = f.read().count('CREATE TABLE')
    with open('data_tenant.sql') as f:
        tenant_tables = f.read().count('CREATE TABLE')

    print(f"   • Public schema: {public_tables} tables")
    print(f"   • Tenant schema: {tenant_tables} tables")

    print("\n📋 Next steps:")
    print("   1. Verify dumps:")
    print("      head -50 data_public.sql")
    print("      head -50 data_tenant.sql")
    print("   2. Test schema creation:")
    print("      python test_schema_creation.py")
    print("   3. Build desktop app:")
    print("      python build_nuitka.py --debug")

    return True


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)