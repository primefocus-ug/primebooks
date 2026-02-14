#!/usr/bin/env python3
"""
Production Sync Diagnostic Tool
Identifies exactly where and why sync fails
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')
os.environ['DESKTOP_MODE'] = 'true'
os.environ['DEBUG'] = 'False'

import django
django.setup()

from django.conf import settings
from django.db import connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_sql_file():
    """Check if SQL dump file exists and is readable"""
    print("\n" + "=" * 70)
    print("1️⃣  CHECKING SQL DUMP FILE")
    print("=" * 70)
    
    # Check where auth.py would look for the file
    auth_file = Path(__file__).parent / 'primebooks' / 'auth.py'
    
    if getattr(sys, 'frozen', False):
        sql_path = Path(sys._MEIPASS) / 'data_tenant.sql'
        print(f"  Mode: FROZEN (PyInstaller)")
    else:
        sql_path = auth_file.parent.parent / 'data_tenant.sql'
        print(f"  Mode: NOT FROZEN (running from source)")
    
    print(f"  Auth file: {auth_file}")
    print(f"  SQL path: {sql_path}")
    print(f"  SQL exists: {sql_path.exists()}")
    
    if sql_path.exists():
        size = sql_path.stat().st_size
        print(f"  SQL size: {size:,} bytes ({size / 1024:.1f} KB)")
        
        # Try to read first few lines
        try:
            with open(sql_path, 'r') as f:
                first_lines = [next(f) for _ in range(5)]
            print(f"  ✅ SQL file is readable")
            print(f"  First line: {first_lines[0][:80]}")
            return True
        except Exception as e:
            print(f"  ❌ Cannot read SQL file: {e}")
            return False
    else:
        print(f"  ❌ SQL file NOT FOUND")
        print(f"\n  Expected location: {sql_path}")
        print(f"  Current directory: {Path.cwd()}")
        
        # Search for it
        print(f"\n  Searching for data_tenant.sql...")
        for p in Path.cwd().rglob('data_tenant.sql'):
            print(f"    Found: {p}")
        
        return False


def test_schema_creation_directly():
    """Test schema creation without authentication"""
    print("\n" + "=" * 70)
    print("2️⃣  TESTING DIRECT SCHEMA CREATION")
    print("=" * 70)
    
    from primebooks.schema_loader import (
        create_tenant_schema,
        check_schema_exists,
        get_schema_tables,
        drop_schema_if_exists
    )
    
    test_schema = "test_diagnostic"
    
    # Clean up if exists
    if check_schema_exists(test_schema):
        print(f"  Cleaning up existing test schema...")
        drop_schema_if_exists(test_schema)
    
    # Find SQL file
    if getattr(sys, 'frozen', False):
        sql_path = Path(sys._MEIPASS) / 'data_tenant.sql'
    else:
        sql_path = Path(__file__).parent / 'data_tenant.sql'
    
    if not sql_path.exists():
        print(f"  ❌ SQL file not found: {sql_path}")
        return False
    
    print(f"  Creating schema from SQL: {sql_path}")
    
    try:
        # Create schema
        success = create_tenant_schema(test_schema, sql_path)
        
        if success:
            print(f"  ✅ Schema creation returned True")
            
            # Check tables
            tables = get_schema_tables(test_schema)
            print(f"  📊 Tables created: {len(tables)}")
            
            if len(tables) > 0:
                print(f"  Sample tables: {tables[:5]}")
                print(f"  ✅ SCHEMA CREATION WORKS!")
                
                # Clean up
                drop_schema_if_exists(test_schema)
                return True
            else:
                print(f"  ❌ Schema created but NO TABLES")
                return False
        else:
            print(f"  ❌ Schema creation returned False")
            return False
            
    except Exception as e:
        print(f"  ❌ Schema creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_authentication_flow():
    """Test the actual authentication flow"""
    print("\n" + "=" * 70)
    print("3️⃣  TESTING AUTHENTICATION FLOW")
    print("=" * 70)
    
    email = input("  Enter email: ")
    password = input("  Enter password: ")
    subdomain = input("  Enter subdomain: ")
    
    from primebooks.auth import DesktopAuthManager
    from primebooks.schema_loader import get_schema_tables, drop_schema_if_exists
    
    # Clean up schema first
    print(f"\n  Cleaning up schema '{subdomain}' if it exists...")
    drop_schema_if_exists(subdomain)
    
    print(f"\n  Attempting authentication...")
    
    auth_manager = DesktopAuthManager()
    auth_manager.base_domain = 'primebooks.sale'
    
    success, result = auth_manager.authenticate(email, password, subdomain)
    
    if not success:
        print(f"  ❌ Authentication failed: {result}")
        return False
    
    print(f"  ✅ Authentication succeeded")
    
    # Check schema
    company_info = auth_manager.get_company_info()
    schema_name = company_info['schema_name']
    
    print(f"\n  Checking schema: {schema_name}")
    tables = get_schema_tables(schema_name)
    print(f"  📊 Tables in schema: {len(tables)}")
    
    if len(tables) > 0:
        print(f"  Sample tables: {tables[:10]}")
        print(f"  ✅ AUTHENTICATION CREATES TABLES!")
        return True
    else:
        print(f"  ❌ AUTHENTICATION FAILED TO CREATE TABLES")
        print(f"\n  This means the SQL dump is not being applied during auth")
        return False


def test_sync_manager():
    """Test if sync manager can connect"""
    print("\n" + "=" * 70)
    print("4️⃣  TESTING SYNC MANAGER CONNECTION")
    print("=" * 70)
    
    from primebooks.auth import DesktopAuthManager
    
    auth_manager = DesktopAuthManager()
    
    if not auth_manager.is_authenticated():
        print(f"  ⚠️  Not authenticated - run test 3 first")
        return False
    
    token = auth_manager.get_auth_token()
    company_info = auth_manager.get_company_info()
    
    tenant_id = company_info['company_id']
    schema_name = company_info['schema_name']
    subdomain = auth_manager.get_subdomain()
    
    print(f"  Tenant ID: {tenant_id}")
    print(f"  Schema: {schema_name}")
    print(f"  Subdomain: {subdomain}")
    
    from primebooks.sync import SyncManager
    
    sync_manager = SyncManager(tenant_id, schema_name, token)
    sync_manager.server_url = f"https://{subdomain}.primebooks.sale"
    
    print(f"  Server URL: {sync_manager.server_url}")
    
    if sync_manager.is_online():
        print(f"  ✅ Server is reachable")
        return True
    else:
        print(f"  ❌ Server is not reachable")
        return False


def main():
    print("\n" + "=" * 70)
    print("🔬 PRODUCTION SYNC DIAGNOSTIC TOOL")
    print("=" * 70)
    print("\nThis will help identify why sync fails in production\n")
    
    # Test 1: SQL file
    sql_ok = check_sql_file()
    
    if not sql_ok:
        print("\n❌ CRITICAL: SQL file not found or not readable")
        print("   Fix this before continuing")
        return
    
    # Test 2: Direct schema creation
    print("\n" + "=" * 70)
    input("Press ENTER to test direct schema creation...")
    
    schema_ok = test_schema_creation_directly()
    
    if not schema_ok:
        print("\n❌ CRITICAL: Direct schema creation failed")
        print("   This means the SQL dump itself has issues")
        print("   OR the schema_loader.py has bugs")
        return
    
    # Test 3: Authentication flow
    print("\n" + "=" * 70)
    input("Press ENTER to test authentication flow...")
    
    auth_ok = test_authentication_flow()
    
    if not auth_ok:
        print("\n❌ CRITICAL: Authentication doesn't create tables")
        print("   Even though direct creation works!")
        print("   This means there's a bug in auth.py")
        print("\n   LIKELY CAUSE:")
        print("   - Schema is created by Django before SQL dump runs")
        print("   - SQL dump sees existing schema and skips creation")
        print("   - Schema ends up empty")
        return
    
    # Test 4: Sync manager
    print("\n" + "=" * 70)
    input("Press ENTER to test sync manager...")
    
    sync_ok = test_sync_manager()
    
    if sync_ok:
        print("\n✅ ALL TESTS PASSED!")
        print("   Sync should work now")
    else:
        print("\n⚠️  Auth works but sync manager can't connect")
        print("   Check network/firewall")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)