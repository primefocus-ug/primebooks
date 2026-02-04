#!/usr/bin/env python3
"""
ULTIMATE PyInstaller Build - EVERYTHING INCLUDED (FIXED)
✅ Guaranteed to include ALL packages and submodules
✅ Works on Windows/macOS/Linux
✅ No more "module not found" errors
✅ FIXED: Includes primebooks directory as data
"""
import PyInstaller.__main__
import sys
import os
import shutil
import platform
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

# Detect OS
IS_WINDOWS = platform.system() == 'Windows'
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'
OS_NAME = 'Windows' if IS_WINDOWS else 'macOS' if IS_MACOS else 'Linux'

print("=" * 80)
print(f"🚀 ULTIMATE BUILD - Include EVERYTHING - {OS_NAME}")
print("=" * 80)
print("💡 Philosophy: Heavy is OK - Working is ESSENTIAL\n")

# ============================================================================
# STEP 1: DISCOVER EVERYTHING
# ============================================================================
print("📦 Step 1: Discovering ALL modules...")

# Virtual environment packages
if IS_WINDOWS:
    site_packages = Path(sys.prefix) / 'Lib' / 'site-packages'
else:
    python_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = Path(sys.prefix) / 'lib' / python_ver / 'site-packages'

print(f"  Site-packages: {site_packages}")

# Primebooks modules
primebooks_dir = BASE_DIR / 'primebooks'
primebooks_modules = []
if primebooks_dir.exists():
    print(f"\n  📂 Scanning primebooks directory: {primebooks_dir}")
    for item in primebooks_dir.glob('*.py'):
        if item.name != '__init__.py':
            module_name = f'primebooks.{item.stem}'
            primebooks_modules.append(module_name)
            print(f"     • {module_name}")

    # Check for postgres_manager specifically
    postgres_manager = primebooks_dir / 'postgres_manager.py'
    if postgres_manager.exists():
        print(f"\n  ✅ VERIFIED: primebooks/postgres_manager.py exists")
    else:
        print(f"\n  ⚠️  WARNING: primebooks/postgres_manager.py NOT FOUND")
else:
    print(f"  ❌ WARNING: primebooks directory not found at {primebooks_dir}")

print(f"\n  Total primebooks modules: {len(primebooks_modules)}")

# Django apps
django_apps = []
for item in BASE_DIR.iterdir():
    if item.is_dir() and not item.name.startswith('.'):
        if (item / '__init__.py').exists() or (item / 'models.py').exists():
            exclude = ['dist', 'build', 'venv', 'env', '__pycache__',
                       'staticfiles', 'media', 'logs', '.git', '.venv']
            if item.name not in exclude:
                django_apps.append(item.name)
print(f"  Django apps: {len(django_apps)}")

# ============================================================================
# STEP 2: CLEAN BUILD
# ============================================================================
print("\n🧹 Step 2: Cleaning previous builds...")
for dir_name in ['dist', 'build']:
    dir_path = BASE_DIR / dir_name
    if dir_path.exists():
        shutil.rmtree(dir_path)
        print(f"  ✅ Removed {dir_name}/")

for spec in BASE_DIR.glob('*.spec'):
    spec.unlink()
    print(f"  ✅ Removed {spec.name}")

# ============================================================================
# STEP 3: BUILD COMMAND
# ============================================================================
print("\n🔧 Step 3: Building command - INCLUDE EVERYTHING...")

args = [
    str(BASE_DIR / 'main.py'),
    '--name=PrimeBooks',
    '--onefile',
    '--clean',
    '--noconfirm',
    '--log-level=INFO',
    f'--paths={BASE_DIR}',
    f'--paths={BASE_DIR / "tenancy"}',
    f'--paths={BASE_DIR / "primebooks"}',
    f'--paths={site_packages}',
]

# Collect all submodules of local packages (guaranteed)
args.append('--collect-submodules=primebooks')
args.append('--collect-submodules=tenancy')

# Hidden imports - tenancy
tenancy_modules = [
    'tenancy',
    'tenancy.settings',
    'tenancy.urls',
    'tenancy.wsgi',
    'tenancy.middleware',
    'tenancy.aelery',
]
for mod in tenancy_modules:
    args.append(f'--hidden-import={mod}')

# Hidden imports - primebooks (EXPLICIT)
args.append('--hidden-import=primebooks')
for mod in primebooks_modules:
    args.append(f'--hidden-import={mod}')

# Hidden imports - Django apps
for app in django_apps:
    args.append(f'--hidden-import={app}')
    app_path = BASE_DIR / app
    for submod in ['models', 'views', 'urls', 'admin', 'signals', 'tasks',
                   'forms', 'serializers', 'middleware', 'backends', 'context_processors']:
        if (app_path / f'{submod}.py').exists():
            args.append(f'--hidden-import={app}.{submod}')

# Hidden imports - requirements.txt
requirements_file = BASE_DIR / 'requirements.txt'
if requirements_file.exists():
    print("\n  📋 Reading requirements.txt...")
    package_count = 0
    with open(requirements_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                package = line.split('==')[0].split('>=')[0].split('[')[0].strip()
                module = package.replace('-', '_').lower()
                args.append(f'--hidden-import={module}')
                package_count += 1
    print(f"     ✅ Added {package_count} packages")

# Critical modules
critical = [
    # Django core
    'django', 'django.core', 'django.db', 'django.db.backends.postgresql',
    'django.contrib.auth', 'django.contrib.sessions', 'django.contrib.admin',

    # django-tenants
    'django_tenants', 'django_tenants.utils', 'django_tenants.postgresql_backend',
    'django_tenants.management', 'django_tenants.management.commands',
    'django_tenants.management.commands.migrate_schemas',
    'django_tenants.management.commands.create_tenant',
    'django_tenants.management.commands.create_superuser_schemas',

    # psycopg2 & cryptography
    'psycopg2', 'psycopg2._psycopg', 'cryptography', 'cryptography.fernet',

    # Celery (CRITICAL)
    'celery', 'celery.app', 'celery.app.base', 'celery.worker',
    'celery.exceptions', 'celery.local', 'celery.utils', 'celery.utils.log',
    'kombu', 'kombu.transport', 'billiard', 'amqp', 'vine',

    # PyQt6
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui',
    'PyQt6.QtWebEngineWidgets',
]
for imp in critical:
    args.append(f'--hidden-import={imp}')

# Collect-all (deep inclusion)
for pkg in ['celery', 'kombu', 'billiard', 'django', 'django_tenants', 'psycopg2']:
    args.append(f'--collect-all={pkg}')

# Data directories - THE CRITICAL FIX!
data_dirs = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('locale', 'locale'),
    ('primebooks', 'primebooks'),  # ← THIS IS THE KEY FIX!
]

# Add Django app templates too
for app in django_apps:
    app_templates = BASE_DIR / app / 'templates'
    if app_templates.exists():
        data_dirs.append((app_templates, f'{app}/templates'))

print("\n  ✅ Adding data directories:")
for src, dst in data_dirs:
    src_path = BASE_DIR / src if isinstance(src, str) else src
    if src_path.exists():
        if IS_WINDOWS:
            args.append(f'--add-data={src_path};{dst}')
        else:
            args.append(f'--add-data={src_path}:{dst}')
        print(f"    • {src_path.name} → {dst}")

# ============================================================================
# STEP 4: RUN BUILD
# ============================================================================
print("\n" + "=" * 80)
print("🔨 Step 4: Running PyInstaller...")
print("=" * 80)

try:
    PyInstaller.__main__.run(args)

    # Output path
    dist_dir = BASE_DIR / 'dist'
    exe_path = dist_dir / ('PrimeBooks.exe' if IS_WINDOWS else 'PrimeBooks')

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 80)
        print("✅ BUILD COMPLETE!")
        print("=" * 80)
        print(f"📦 Executable: {exe_path}")
        print(f"💾 Size: {size_mb:.1f} MB")

        if not IS_WINDOWS:
            os.chmod(exe_path, 0o755)
            print("🔒 Made executable")

        print("\n📊 Included modules:")
        print(f"   • primebooks submodules: {len(primebooks_modules)}")
        print(f"   • Django apps: {len(django_apps)}")

        print(f"\n🚀 Run:")
        if IS_WINDOWS:
            print(f"   cd dist && PrimeBooks.exe")
        else:
            print(f"   cd dist && ./PrimeBooks")

    else:
        print("\n❌ Build failed - executable not found")
        sys.exit(1)

except Exception as e:
    print(f"\n❌ BUILD FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("🎉 BUILD COMPLETE - primebooks.postgres_manager should now be found!")
print("=" * 80)