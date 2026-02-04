#!/usr/bin/env python3
"""
EMERGENCY REBUILD - Explicit Module Inclusion
Fixes: No module named 'primebooks.postgres_manager'
"""
import PyInstaller.__main__
import sys
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

print("=" * 80)
print("🚨 EMERGENCY REBUILD - Fixing Missing Modules")
print("=" * 80)

# ============================================================================
# VERIFY primebooks DIRECTORY STRUCTURE
# ============================================================================
print("\n🔍 Verifying primebooks directory...")

primebooks_dir = BASE_DIR / 'primebooks'
if not primebooks_dir.exists():
    print(f"❌ ERROR: primebooks directory not found at {primebooks_dir}")
    sys.exit(1)

print(f"  ✅ Found: {primebooks_dir}")

# List all Python files in primebooks
print("\n📦 Python modules in primebooks/:")
primebooks_modules = []
for item in primebooks_dir.glob('*.py'):
    if item.name != '__init__.py':
        module_name = item.stem
        primebooks_modules.append(f'primebooks.{module_name}')
        print(f"  • primebooks.{module_name}")

if not primebooks_modules:
    print("  ⚠️  No Python modules found in primebooks/")

# Check for postgres_manager specifically
postgres_manager = primebooks_dir / 'postgres_manager.py'
if postgres_manager.exists():
    print(f"\n  ✅ FOUND: primebooks/postgres_manager.py")
else:
    print(f"\n  ❌ MISSING: primebooks/postgres_manager.py")
    print("     This is the module that's failing!")

# ============================================================================
# AUTO-DISCOVER ALL DJANGO APPS
# ============================================================================
print("\n📦 Discovering Django apps...")

django_apps = []
for item in BASE_DIR.iterdir():
    if item.is_dir() and not item.name.startswith('.'):
        if (item / '__init__.py').exists() or (item / 'models.py').exists():
            if item.name not in ['dist', 'build', 'venv', 'env', '__pycache__',
                                 'staticfiles', 'media', 'logs', '.git']:
                django_apps.append(item.name)
                print(f"  ✅ {item.name}")

# ============================================================================
# CLEAN BUILD
# ============================================================================
print("\n🧹 Cleaning previous build...")

for dir_name in ['dist', 'build']:
    dir_path = BASE_DIR / dir_name
    if dir_path.exists():
        shutil.rmtree(dir_path)

spec_file = BASE_DIR / 'main.spec'
if spec_file.exists():
    spec_file.unlink()

# ============================================================================
# BUILD WITH EXPLICIT MODULE INCLUSION
# ============================================================================
print("\n🔧 Building PyInstaller command with EXPLICIT module inclusion...")

args = [
    str(BASE_DIR / 'main.py'),
    '--name=PrimeBooks',
    '--onefile',
    f'--paths={BASE_DIR}',
    f'--paths={BASE_DIR / "tenancy"}',
    f'--paths={BASE_DIR / "primebooks"}',  # Explicit primebooks path
]

# Add tenancy
args.extend([
    # django-tenants management commands (CRITICAL)
    '--hidden-import=django_tenants.management',
    '--hidden-import=django_tenants.management.commands',
    '--hidden-import=django_tenants.management.commands.migrate_schemas',
    '--hidden-import=django_tenants.management.commands.create_tenant',
    '--hidden-import=django_tenants.management.commands.create_superuser_schemas',

    '--hidden-import=tenancy',
    '--hidden-import=tenancy.middleware',
    '--hidden-import=tenancy.aelery',
    '--hidden-import=tenancy.settings',
    '--hidden-import=tenancy.urls',
    '--hidden-import=tenancy.wsgi',
])

print("\n  Adding tenancy modules:")
print("    • tenancy")
print("    • tenancy.settings")
print("    • tenancy.urls")
print("    • tenancy.wsgi")

# EXPLICITLY add ALL primebooks submodules
print("\n  Adding primebooks modules (EXPLICIT):")
for module in primebooks_modules:
    args.append(f'--hidden-import={module}')
    print(f"    • {module}")

# Also add primebooks itself
args.append('--hidden-import=primebooks')
args.append('--collect-all=celery')
args.append('--collect-all=kombu')
args.append('--collect-all=billiard')

print(f"    • primebooks")

# Add ALL Django apps
print("\n  Adding Django apps:")
for app in django_apps:
    args.append(f'--hidden-import={app}')
    print(f"    • {app}")

    # Add submodules
    app_path = BASE_DIR / app
    for submodule in ['models', 'views', 'urls', 'admin', 'signals', 'tasks']:
        if (app_path / f'{submodule}.py').exists():
            args.append(f'--hidden-import={app}.{submodule}')

# Read requirements.txt
print("\n  Reading requirements.txt...")
requirements_file = BASE_DIR / 'requirements.txt'
if requirements_file.exists():
    with open(requirements_file, 'r') as f:
        package_count = 0
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                package = line.split('==')[0].split('>=')[0].split('[')[0].strip()
                module = package.replace('-', '_').lower()
                args.append(f'--hidden-import={module}')
                package_count += 1
    print(f"    ✅ Added {package_count} packages from requirements.txt")

# Critical imports
critical = [
    'django',
    'django.core',
    'django.db',
    'django.db.backends.postgresql',
    'django.contrib.auth',

    # django-tenants core
    'django_tenants',
    'django_tenants.utils',
    'django_tenants.postgresql_backend',

    # django-tenants management commands (FIX)
    'django_tenants.management',
    'django_tenants.management.commands',
    'django_tenants.management.commands.migrate_schemas',
    'django_tenants.management.commands.create_tenant',
    'django_tenants.management.commands.create_superuser_schemas',

    'psycopg2',
    'psycopg2._psycopg',
    'cryptography',
    'cryptography.fernet',
    # Celery (CRITICAL for frozen apps)
    'celery',
    'celery.app',
    'celery.app.base',
    'celery.exceptions',
    'celery.local',
    'celery.utils',
    'celery.utils.log',
    'celery.utils.time',
    'celery.worker',
    'celery.worker.request',
    'kombu',
    'kombu.transport',
    'billiard',

    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtWidgets',
    'PyQt6.QtGui',
    'PyQt6.QtWebEngineWidgets',
]


print("\n  Adding critical imports:")
for imp in critical:
    args.append(f'--hidden-import={imp}')
    print(f"    • {imp}")

# Add data directories
data_dirs = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('locale', 'locale'),
    ('primebooks', 'primebooks'),  # Include entire primebooks directory
]

print("\n  Adding Django app templates:")
for app in django_apps:
    app_templates = BASE_DIR / app / 'templates'
    if app_templates.exists():
        args.append(f'--add-data={app_templates}:{app}/templates')
        print(f"    • {app}/templates")

print("\n  Adding data directories:")
for src, dst in data_dirs:
    src_path = BASE_DIR / src
    if src_path.exists():
        args.append(f'--add-data={src_path}:{dst}')
        print(f"    • {src} → {dst}")

# Build options
args.extend([
    '--clean',
    '--noconfirm',
    '--log-level=INFO',
    '--debug=imports',  # Debug import issues
])

# ============================================================================
# RUN BUILD
# ============================================================================
print("\n" + "=" * 80)
print("🔨 Running PyInstaller...")
print("=" * 80)

try:
    PyInstaller.__main__.run(args)

    exe_path = BASE_DIR / 'dist' / 'PrimeBooks'

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)

        print("\n" + "=" * 80)
        print("✅ BUILD COMPLETE!")
        print("=" * 80)
        print(f"\n📦 Executable: {exe_path}")
        print(f"💾 Size: {size_mb:.1f} MB")

        os.chmod(exe_path, 0o755)

        print(f"\n📊 Modules included:")
        print(f"   • primebooks submodules: {len(primebooks_modules)}")
        print(f"   • Django apps: {len(django_apps)}")

        print(f"\n🧪 Testing for postgres_manager...")

        # Quick test
        test_script = f"""
import sys
sys.path.insert(0, '{BASE_DIR}')
try:
    from primebooks.postgres_manager import EmbeddedPostgresManager
    print("   ✅ postgres_manager import: SUCCESS")
except ImportError as e:
    print(f"   ❌ postgres_manager import: FAILED - {{e}}")
"""
        exec(test_script)

        print(f"\n🚀 To run:")
        print(f"   cd {BASE_DIR / 'dist'}")
        print(f"   ./PrimeBooks")

    else:
        print("\n❌ Build failed - executable not found")
        sys.exit(1)

except Exception as e:
    print(f"\n❌ BUILD FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)