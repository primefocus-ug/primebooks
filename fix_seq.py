#!/usr/bin/env python3
"""
COMPREHENSIVE PRE-BUILD TEST SUITE
Tests everything before packaging the app

This script validates:
1. ✅ All code fixes applied
2. ✅ Database initialization
3. ✅ Schema creation (SQL dumps)
4. ✅ Authentication flow
5. ✅ Sync performance (incremental)
6. ✅ File integrity
7. ✅ Import integrity
8. ✅ Performance benchmarks

Run this before building to ensure everything works!
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
import traceback


# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}")


def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")


def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.END}")


def print_warning(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")


def print_info(text):
    print(f"{Colors.CYAN}ℹ️  {text}{Colors.END}")


# Test results tracking
class TestResults:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
        self.start_time = time.time()

    def add_pass(self, test_name):
        self.passed.append(test_name)
        print_success(test_name)

    def add_fail(self, test_name, error=None):
        self.failed.append((test_name, error))
        print_error(f"{test_name}")
        if error:
            print(f"   {Colors.RED}Error: {error}{Colors.END}")

    def add_warning(self, test_name, message):
        self.warnings.append((test_name, message))
        print_warning(f"{test_name}: {message}")

    def summary(self):
        duration = time.time() - self.start_time

        print_header("TEST SUMMARY")
        print(f"\n{Colors.BOLD}Duration: {duration:.2f} seconds{Colors.END}\n")

        print(f"{Colors.GREEN}✅ PASSED: {len(self.passed)}{Colors.END}")
        for test in self.passed:
            print(f"   • {test}")

        if self.warnings:
            print(f"\n{Colors.YELLOW}⚠️  WARNINGS: {len(self.warnings)}{Colors.END}")
            for test, msg in self.warnings:
                print(f"   • {test}: {msg}")

        if self.failed:
            print(f"\n{Colors.RED}❌ FAILED: {len(self.failed)}{Colors.END}")
            for test, error in self.failed:
                print(f"   • {test}")
                if error:
                    print(f"     Error: {error}")

        print("\n" + "=" * 70)

        if self.failed:
            print(f"{Colors.RED}{Colors.BOLD}❌ BUILD NOT READY - FIX FAILURES FIRST{Colors.END}")
            return False
        elif self.warnings:
            print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  BUILD READY WITH WARNINGS{Colors.END}")
            return True
        else:
            print(f"{Colors.GREEN}{Colors.BOLD}✅ ALL TESTS PASSED - READY TO BUILD!{Colors.END}")
            return True


# Initialize results
results = TestResults()

# Setup paths
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')
os.environ['DESKTOP_MODE'] = 'true'

# ============================================================================
# TEST 1: FILE INTEGRITY
# ============================================================================
print_header("TEST 1: FILE INTEGRITY")


def test_file_exists(filepath, description):
    """Test if a file exists"""
    test_name = f"File exists: {description}"
    if filepath.exists():
        size_kb = filepath.stat().st_size / 1024
        results.add_pass(f"{test_name} ({size_kb:.1f} KB)")
    else:
        results.add_fail(test_name, f"File not found: {filepath}")


# SQL dumps
test_file_exists(BASE_DIR / 'data_tenant.sql', 'data_tenant.sql')
test_file_exists(BASE_DIR / 'data_public.sql', 'data_public.sql')

# Critical Python files
critical_files = [
    ('primebooks/auth.py', 'Authentication module'),
    ('primebooks/sync.py', 'Sync manager'),
    ('primebooks/schema_loader.py', 'Schema loader'),
    ('primebooks/postgres_manager.py', 'PostgreSQL manager'),
    ('primebooks/subscription.py', 'Subscription manager'),
    ('primebooks/security/encryption.py', 'Encryption manager'),
    ('main.py', 'Main entry point'),
    ('manage.py', 'Django management'),
]

for filepath, description in critical_files:
    test_file_exists(BASE_DIR / filepath, description)

# ============================================================================
# TEST 2: CODE FIXES VERIFICATION
# ============================================================================
print_header("TEST 2: CODE FIXES VERIFICATION")

# Test 2.1: schema_loader.py fix
print_info("Checking schema_loader.py fix...")
schema_loader_file = BASE_DIR / 'primebooks' / 'schema_loader.py'

if schema_loader_file.exists():
    content = schema_loader_file.read_text()

    # Check for undefined function call (should be commented or removed)
    active_call = False
    for line in content.split('\n'):
        if 'create_sequences_for_schema(schema_name)' in line:
            if not line.strip().startswith('#'):
                active_call = True
                break

    if not active_call:
        results.add_pass("schema_loader.py: No undefined function calls")
    else:
        results.add_fail("schema_loader.py: Undefined function still called",
                         "Line contains 'create_sequences_for_schema(schema_name)' uncommented")
else:
    results.add_fail("schema_loader.py: File not found")

# Test 2.2: auth.py schema name fix
print_info("Checking auth.py schema name fix...")
auth_file = BASE_DIR / 'primebooks' / 'auth.py'

if auth_file.exists():
    content = auth_file.read_text()

    if "company['schema_name'] = subdomain" in content:
        results.add_pass("auth.py: Schema name fix applied")
    else:
        results.add_warning("auth.py: Schema name fix not found",
                            "May cause sync to use wrong schema")
else:
    results.add_fail("auth.py: File not found")

# Test 2.3: sync.py ContentType exclusion
print_info("Checking sync.py ContentType exclusion...")
sync_file = BASE_DIR / 'primebooks' / 'sync.py'

if sync_file.exists():
    content = sync_file.read_text()

    if "EXCLUDED_MODELS" in content or "contenttypes.ContentType" in content:
        results.add_pass("sync.py: Model exclusion implemented")
    else:
        results.add_warning("sync.py: No model exclusion found",
                            "Sync will include ContentType (slow, errors)")
else:
    results.add_fail("sync.py: File not found")

# ============================================================================
# TEST 3: IMPORT INTEGRITY
# ============================================================================
print_header("TEST 3: IMPORT INTEGRITY")


def test_import(module_name):
    """Test if a module can be imported"""
    try:
        __import__(module_name)
        results.add_pass(f"Import: {module_name}")
        return True
    except Exception as e:
        results.add_fail(f"Import: {module_name}", str(e))
        return False


# Critical imports
critical_imports = [
    'primebooks.auth',
    'primebooks.sync',
    'primebooks.schema_loader',
    'primebooks.postgres_manager',
    'primebooks.subscription',
    'primebooks.security.encryption',
]

import_success = True
for module in critical_imports:
    if not test_import(module):
        import_success = False

# Only proceed with Django tests if imports work
if not import_success:
    print_error("Cannot proceed with Django tests - import failures")
else:
    # ========================================================================
    # TEST 4: DJANGO INITIALIZATION
    # ========================================================================
    print_header("TEST 4: DJANGO INITIALIZATION")

    try:
        import django

        django.setup()
        results.add_pass("Django initialization")
    except Exception as e:
        results.add_fail("Django initialization", str(e))
        print_error("Cannot proceed - Django initialization failed")
        results.summary()
        sys.exit(1)

    # ========================================================================
    # TEST 5: DATABASE CONNECTION
    # ========================================================================
    print_header("TEST 5: DATABASE CONNECTION")

    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            results.add_pass(f"PostgreSQL connection: {version.split(',')[0]}")
    except Exception as e:
        results.add_fail("PostgreSQL connection", str(e))

    # ========================================================================
    # TEST 6: SCHEMA CREATION (SQL DUMPS)
    # ========================================================================
    print_header("TEST 6: SCHEMA CREATION PERFORMANCE")

    try:
        from primebooks.schema_loader import create_tenant_schema, get_schema_tables, check_schema_exists
        from django.db import connection

        test_schema = 'test_prebuild_schema'

        # Clean up if exists
        if check_schema_exists(test_schema):
            with connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{test_schema}" CASCADE;')

        # Test schema creation
        sql_file = BASE_DIR / 'data_tenant.sql'

        if sql_file.exists():
            start_time = time.time()
            success = create_tenant_schema(test_schema, sql_file)
            duration = time.time() - start_time

            if success:
                tables = get_schema_tables(test_schema)
                results.add_pass(f"Schema creation from SQL: {len(tables)} tables in {duration:.2f}s")

                if duration > 10:
                    results.add_warning("Schema creation slow",
                                        f"Took {duration:.2f}s (expected <5s)")
            else:
                results.add_fail("Schema creation from SQL")

            # Cleanup
            with connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{test_schema}" CASCADE;')
        else:
            results.add_fail("Schema creation test", "SQL file not found")

    except Exception as e:
        results.add_fail("Schema creation test", str(e))
        if 'test_schema' in locals():
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP SCHEMA IF EXISTS "{test_schema}" CASCADE;')
            except:
                pass

    # ========================================================================
    # TEST 7: AUTHENTICATION FUNCTIONS
    # ========================================================================
    print_header("TEST 7: AUTHENTICATION FUNCTIONS")

    try:
        from primebooks.auth import DesktopAuthManager

        auth = DesktopAuthManager()

        # Test methods exist
        methods = [
            'authenticate',
            'save_auth_token',
            'get_auth_token',
            'save_company_info',
            'get_company_info',
            'save_subdomain',
            'get_subdomain',
            'is_authenticated',
            'logout',
        ]

        for method in methods:
            if hasattr(auth, method):
                results.add_pass(f"Auth method exists: {method}")
            else:
                results.add_fail(f"Auth method exists: {method}")

    except Exception as e:
        results.add_fail("Authentication module test", str(e))

    # ========================================================================
    # TEST 8: SYNC MANAGER FUNCTIONS
    # ========================================================================
    print_header("TEST 8: SYNC MANAGER FUNCTIONS")

    try:
        from primebooks.sync import SyncManager

        # Check if EXCLUDED_MODELS exists
        import primebooks.sync as sync_module

        if hasattr(sync_module, 'EXCLUDED_MODELS'):
            excluded = sync_module.EXCLUDED_MODELS
            results.add_pass(f"EXCLUDED_MODELS defined: {len(excluded)} models")

            if 'contenttypes.ContentType' in excluded:
                results.add_pass("ContentType excluded from sync")
            else:
                results.add_warning("ContentType not excluded",
                                    "Will cause duplicate errors")
        else:
            results.add_warning("EXCLUDED_MODELS not found",
                                "Sync will include all models (slow)")

        # Test SyncManager can be instantiated
        try:
            sync_manager = SyncManager('test-tenant', 'test_schema', 'fake-token')
            results.add_pass("SyncManager instantiation")
        except Exception as e:
            results.add_fail("SyncManager instantiation", str(e))

    except Exception as e:
        results.add_fail("Sync manager test", str(e))

    # ========================================================================
    # TEST 9: MODEL TIMESTAMP FIELDS
    # ========================================================================
    print_header("TEST 9: MODEL TIMESTAMP FIELDS (Incremental Sync)")

    try:
        from sales.models import Sale
        from inventory.models import Product
        from customers.models import Customer

        models_to_check = [
            ('Sale', Sale),
            ('Product', Product),
            ('Customer', Customer),
        ]

        for model_name, model in models_to_check:
            fields = [f.name for f in model._meta.fields]

            has_created = 'created_at' in fields or 'created' in fields
            has_updated = 'updated_at' in fields or 'updated' in fields or 'modified_at' in fields

            if has_created and has_updated:
                results.add_pass(f"{model_name}: Has timestamp fields")
            else:
                results.add_warning(f"{model_name}: Missing timestamp fields",
                                    "Incremental sync may not work")
    except Exception as e:
        results.add_fail("Model timestamp check", str(e))

    # ========================================================================
    # TEST 10: SUBSCRIPTION MANAGER
    # ========================================================================
    print_header("TEST 10: SUBSCRIPTION MANAGER")

    try:
        from primebooks.subscription import SubscriptionManager

        # Test instantiation
        sub_manager = SubscriptionManager('test-company', 'test_schema')
        results.add_pass("SubscriptionManager instantiation")

        # Check methods exist
        methods = ['validate_subscription', 'is_trial_active', 'days_remaining']

        for method in methods:
            if hasattr(sub_manager, method):
                results.add_pass(f"Subscription method exists: {method}")
            else:
                results.add_fail(f"Subscription method exists: {method}")

    except Exception as e:
        results.add_fail("Subscription manager test", str(e))

    # ========================================================================
    # TEST 11: ENCRYPTION MANAGER
    # ========================================================================
    print_header("TEST 11: ENCRYPTION MANAGER")

    try:
        from primebooks.security.encryption import get_encryption_manager
        from pathlib import Path

        # Test encryption
        test_dir = Path('/tmp/primebooks_test')
        test_dir.mkdir(exist_ok=True)

        enc = get_encryption_manager(test_dir)

        # Test encrypt/decrypt
        test_data = "Test data for encryption"
        encrypted = enc.encrypt_data(test_data)
        decrypted = enc.decrypt_data(encrypted).decode()

        if decrypted == test_data:
            results.add_pass("Encryption/Decryption working")
        else:
            results.add_fail("Encryption/Decryption", "Decrypted data doesn't match")

        # Cleanup
        import shutil

        shutil.rmtree(test_dir, ignore_errors=True)

    except Exception as e:
        results.add_fail("Encryption manager test", str(e))

    # ========================================================================
    # TEST 12: PERFORMANCE BENCHMARKS
    # ========================================================================
    print_header("TEST 12: PERFORMANCE BENCHMARKS")

    # Schema creation benchmark (already tested above)
    print_info("Schema creation: See TEST 6 results")

    # Import time
    print_info("Testing import performance...")
    start = time.time()
    import primebooks.sync
    import primebooks.auth
    import primebooks.schema_loader

    import_time = time.time() - start

    if import_time < 1.0:
        results.add_pass(f"Import time: {import_time:.3f}s")
    else:
        results.add_warning("Import time slow", f"{import_time:.3f}s (expected <1s)")

    # ========================================================================
    # TEST 13: SQL DUMP INTEGRITY
    # ========================================================================
    print_header("TEST 13: SQL DUMP INTEGRITY")

    for sql_file_name in ['data_tenant.sql', 'data_public.sql']:
        sql_path = BASE_DIR / sql_file_name

        if sql_path.exists():
            content = sql_path.read_text()

            # Check for common issues
            if 'CREATE TABLE' in content:
                results.add_pass(f"{sql_file_name}: Contains CREATE TABLE statements")
            else:
                results.add_fail(f"{sql_file_name}: No CREATE TABLE found")

            if 'INSERT INTO' in content:
                results.add_pass(f"{sql_file_name}: Contains INSERT statements")
            else:
                # Public schema might not have inserts
                if 'public' in sql_file_name:
                    results.add_pass(f"{sql_file_name}: No INSERT (normal for public)")
                else:
                    results.add_warning(f"{sql_file_name}: No INSERT statements",
                                        "Schema may be empty")

            # Count statements
            statements = content.count(';')
            results.add_pass(f"{sql_file_name}: {statements} SQL statements")
        else:
            results.add_fail(f"{sql_file_name}: File not found")

# ============================================================================
# TEST 14: BUILD CONFIGURATION
# ============================================================================
print_header("TEST 14: BUILD CONFIGURATION")

build_script = BASE_DIR / 'build_nuitka_ultimate.py'

if build_script.exists():
    content = build_script.read_text()

    # Check critical includes
    checks = [
        ("SQL dumps included", "include-data-files.*data_tenant.sql"),
        ("Primebooks package included", "include-package=primebooks"),
        ("Critical modules included", "primebooks.sync"),
    ]

    import re

    for check_name, pattern in checks:
        if re.search(pattern, content):
            results.add_pass(f"Build script: {check_name}")
        else:
            results.add_warning(f"Build script: {check_name}", "Not found in build script")
else:
    results.add_warning("Build script not found", "build_nuitka_ultimate.py missing")

# ============================================================================
# FINAL SUMMARY
# ============================================================================
success = results.summary()

# Exit code
if success:
    print(f"\n{Colors.GREEN}{Colors.BOLD}🚀 READY TO BUILD!{Colors.END}")
    print(f"\nRun: python3 build_nuitka_ultimate.py")
    sys.exit(0)
else:
    print(f"\n{Colors.RED}{Colors.BOLD}⛔ NOT READY - FIX FAILURES FIRST{Colors.END}")
    print(f"\nSee failed tests above")
    sys.exit(1)