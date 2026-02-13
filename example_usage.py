#!/usr/bin/env python3
"""
Simple SQL File Test Script
Tests the exported SQL files without requiring Django

This script only checks the SQL file structure and content,
it doesn't actually create schemas (that requires Django).
"""
import sys
from pathlib import Path


def check_file_exists(filepath):
    """Check if file exists and is readable"""
    path = Path(filepath)
    if not path.exists():
        print(f"❌ File not found: {filepath}")
        return False

    if not path.is_file():
        print(f"❌ Not a file: {filepath}")
        return False

    print(f"✅ Found: {filepath}")
    return True


def analyze_sql_file(filepath):
    """Analyze SQL file structure"""
    path = Path(filepath)

    print(f"\n{'='*70}")
    print(f"Analyzing: {path.name}")
    print(f"{'='*70}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Basic statistics
        lines = content.split('\n')
        total_lines = len(lines)
        non_empty_lines = len([l for l in lines if l.strip()])
        comment_lines = len([l for l in lines if l.strip().startswith('--')])

        print(f"\n📊 File Statistics:")
        print(f"  Size: {path.stat().st_size:,} bytes")
        print(f"  Total Lines: {total_lines:,}")
        print(f"  Non-Empty Lines: {non_empty_lines:,}")
        print(f"  Comment Lines: {comment_lines:,}")

        # Count SQL statements
        create_table_count = content.upper().count('CREATE TABLE')
        create_index_count = content.upper().count('CREATE INDEX')
        create_sequence_count = content.upper().count('CREATE SEQUENCE')
        alter_table_count = content.upper().count('ALTER TABLE')
        create_function_count = content.upper().count('CREATE FUNCTION')

        print(f"\n📝 SQL Objects:")
        print(f"  CREATE TABLE: {create_table_count}")
        print(f"  CREATE INDEX: {create_index_count}")
        print(f"  CREATE SEQUENCE: {create_sequence_count}")
        print(f"  ALTER TABLE: {alter_table_count}")
        print(f"  CREATE FUNCTION: {create_function_count}")

        # Check for potential issues
        print(f"\n🔍 Validation Checks:")

        issues = []

        # Check for setval (should be removed by grep)
        if 'pg_catalog.setval' in content:
            issues.append("Contains pg_catalog.setval (should be filtered out)")
        else:
            print(f"  ✅ No pg_catalog.setval statements")

        # Check for psql commands
        psql_commands = [l for l in lines if l.strip().startswith('\\')]
        if psql_commands:
            issues.append(f"Contains {len(psql_commands)} psql commands (\\)")
        else:
            print(f"  ✅ No psql commands")

        # Check schema references
        if 'data_public.sql' in filepath:
            if 'CREATE SCHEMA public' in content or 'CREATE SCHEMA IF NOT EXISTS public' in content:
                print(f"  ✅ Creates public schema")
            else:
                print(f"  ⚠️  No explicit public schema creation")

        if 'data_tenant.sql' in filepath:
            if 'CREATE SCHEMA template' in content or 'CREATE SCHEMA IF NOT EXISTS template' in content:
                print(f"  ✅ Creates template schema")
            else:
                issues.append("Does not create 'template' schema")

            if 'template.' in content:
                template_refs = content.count('template.')
                print(f"  ✅ Found {template_refs} references to 'template.' schema")
            else:
                issues.append("No references to 'template.' schema")

        # Show issues
        if issues:
            print(f"\n⚠️  Potential Issues Found:")
            for issue in issues:
                print(f"  • {issue}")
        else:
            print(f"\n✅ No issues found!")

        # Show sample
        print(f"\n📄 First 20 Lines Preview:")
        print("-" * 70)
        for i, line in enumerate(lines[:20], 1):
            print(f"{i:4d}: {line[:70]}")

        if total_lines > 20:
            print(f"     ... ({total_lines - 20} more lines)")

        return True

    except Exception as e:
        print(f"❌ Error analyzing file: {e}")
        return False


def main():
    """Main function"""
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║  SQL File Verification Tool")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()

    # Files to check
    files = ['data_public.sql', 'data_tenant.sql']

    print("Checking for required files...")
    print()

    found_files = []
    for filepath in files:
        if check_file_exists(filepath):
            found_files.append(filepath)

    print()

    if not found_files:
        print("❌ No SQL files found!")
        print()
        print("Please run the export script first:")
        print("  ./export_all_schemas.sh")
        print()
        return 1

    # Analyze each file
    for filepath in found_files:
        analyze_sql_file(filepath)
        print()

    # Summary
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║  Summary")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()

    if len(found_files) == len(files):
        print("✅ All SQL files found and verified!")
        print()
        print("Next steps:")
        print("  1. These files are ready to use with schema_loader.py")
        print("  2. To test with Django, use:")
        print()
        print("     python manage.py shell")
        print("     >>> from schema_loader import create_tenant_schema")
        print("     >>> create_tenant_schema('test_tenant', 'data_tenant.sql')")
        print()
        print("  3. Or use the management command:")
        print()
        print("     python manage.py create_tenant test_tenant")
        print()
        return 0
    else:
        missing = set(files) - set(found_files)
        print(f"⚠️  Missing files: {', '.join(missing)}")
        print()
        print("Run the export script to generate missing files:")
        print("  ./export_all_schemas.sh")
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())