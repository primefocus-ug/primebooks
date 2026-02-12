#!/usr/bin/env python3
"""
PRODUCTION Nuitka Build - PrimeBooks Desktop (NO CONSOLE)
✅ GUI-only mode (no terminal window)
✅ All console output redirected to log files
✅ End users never see terminal
"""
import sys
import os
import shutil
import platform
import subprocess
from pathlib import Path
import argparse

# ============================================================================
# PARSE COMMAND LINE ARGUMENTS
# ============================================================================
parser = argparse.ArgumentParser(description='Build PrimeBooks Desktop')
parser.add_argument('--debug', action='store_true',
                    help='Enable debug mode (shows console/errors) - FOR DEVELOPERS ONLY')
args = parser.parse_args()

# Set mode - Default to PRODUCTION (no console) unless explicitly debug
DEBUG_MODE = args.debug
PRODUCTION_MODE = not args.debug

BASE_DIR = Path(__file__).parent.absolute()

# Detect OS
IS_WINDOWS = platform.system() == 'Windows'
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'
OS_NAME = 'Windows' if IS_WINDOWS else 'macOS' if IS_MACOS else 'Linux'

print("=" * 80)
print(f"🚀 PRIMEBOOKS NUITKA BUILD - {OS_NAME}")
if DEBUG_MODE:
    print("🐛 DEBUG MODE - Console visible (DEVELOPER BUILD)")
else:
    print("✨ PRODUCTION MODE - GUI only, NO CONSOLE (END USER BUILD)")
print("=" * 80)

# ============================================================================
# STEP 0: CHECK SQL DUMP FILES EXIST
# ============================================================================
print("\n🗄️  Step 0: Checking SQL dump files...")

sql_files_required = [
    'primebooks_tenant.sql',  # Tenant schema template
    # 'primebooks_public.sql',  # Optional: public schema template
]

missing_files = []
for sql_file in sql_files_required:
    sql_path = BASE_DIR / sql_file
    if not sql_path.exists():
        missing_files.append(sql_file)
    else:
        size_kb = sql_path.stat().st_size / 1024
        print(f"  ✅ Found {sql_file} ({size_kb:.1f} KB)")

if missing_files:
    print(f"\n  ⚠️  WARNING: Missing SQL dump files:")
    for f in missing_files:
        print(f"     • {f}")
    print("\n  💡 Generate SQL dumps with:")
    print("     python manage.py dumpdata_schema --schema=template")
    print("\n  The build will continue, but schema creation will fail at runtime!")

    response = input("\n  Continue anyway? (y/N): ")
    if response.lower() != 'y':
        print("  Build cancelled.")
        sys.exit(0)

# ============================================================================
# STEP 1: CHECK NUITKA INSTALLATION
# ============================================================================
print("\n🔍 Step 1: Checking Nuitka installation...")
try:
    result = subprocess.run(['python3', '-m', 'nuitka', '--version'],
                            capture_output=True, text=True)
    print(f"  ✅ Nuitka version: {result.stdout.strip()}")
except:
    print("  ❌ Nuitka not found! Installing...")
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'nuitka', 'ordered-set', 'zstandard'])
    print("  ✅ Nuitka installed")

# Install ccache for faster rebuilds
if IS_LINUX:
    print("\n💡 Installing ccache for faster rebuilds...")
    os.system("sudo apt-get install -y ccache patchelf 2>/dev/null || true")
elif IS_MACOS:
    os.system("brew install ccache 2>/dev/null || true")

# ============================================================================
# STEP 2: DISCOVER ALL APPS AND MODULES
# ============================================================================
print("\n📦 Step 2: Discovering Django-Tenants Apps...")

sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

shared_apps = []
tenant_apps = []
installed_apps = []
custom_apps = []

try:
    import django

    django.setup()
    from django.conf import settings

    shared_apps = list(settings.SHARED_APPS) if hasattr(settings, 'SHARED_APPS') else []
    tenant_apps = list(settings.TENANT_APPS) if hasattr(settings, 'TENANT_APPS') else []
    installed_apps = list(settings.INSTALLED_APPS)

    print(f"\n  ✅ Loaded Django settings")
    print(f"  📋 SHARED_APPS: {len(shared_apps)}")
    print(f"  📋 TENANT_APPS: {len(tenant_apps)}")

    all_apps = set(shared_apps + tenant_apps + installed_apps)
    custom_apps = [app for app in all_apps
                   if not app.startswith('django.')
                   and not app.startswith('django_tenants')
                   and '.' not in app]

    print(f"  📊 Custom apps: {len(custom_apps)}")

except Exception as e:
    print(f"  ⚠️  Could not load Django settings: {e}")
    for item in BASE_DIR.iterdir():
        if item.is_dir() and (item / '__init__.py').exists():
            exclude = ['dist', 'build', 'venv', 'env', '__pycache__', 'staticfiles',
                       'media', 'logs', '.git', '.venv', 'PrimeBooks.build',
                       'PrimeBooks.dist', 'PrimeBooks.onefile-build']
            if item.name not in exclude:
                custom_apps.append(item.name)

# Discover primebooks modules
primebooks_dir = BASE_DIR / 'primebooks'
primebooks_modules = []
if primebooks_dir.exists():
    print(f"\n  📂 Scanning primebooks directory...")
    for item in primebooks_dir.rglob('*.py'):
        if '__pycache__' not in str(item):
            rel_path = item.relative_to(primebooks_dir)
            module_path = str(rel_path.with_suffix('')).replace(os.sep, '.')
            module_name = f'primebooks.{module_path}' if module_path != '__init__' else 'primebooks'
            if module_name not in primebooks_modules:
                primebooks_modules.append(module_name)
                # ✅ Verify critical modules
                if any(x in module_name for x in ['sync_dialogs', 'sync', 'auth', 'schema_loader']):
                    print(f"     ✅ Found critical: {module_name}")
    print(f"  Total primebooks modules: {len(primebooks_modules)}")

# ============================================================================
# STEP 3: CLEAN BUILD
# ============================================================================
print("\n🧹 Step 3: Cleaning previous builds...")
for dir_name in ['dist', 'build', 'PrimeBooks.build', 'PrimeBooks.dist',
                 'PrimeBooks.onefile-build']:
    dir_path = BASE_DIR / dir_name
    if dir_path.exists():
        shutil.rmtree(dir_path)
        print(f"  ✅ Removed {dir_name}/")

# ============================================================================
# STEP 4: BUILD NUITKA COMMAND
# ============================================================================
print("\n🔧 Step 4: Building Nuitka command...")

cmd = [
    sys.executable,
    '-m', 'nuitka',
    str(BASE_DIR / 'main.py'),
    '--standalone',
    '--onefile',
    f'--output-dir={BASE_DIR / "dist"}',
    '--output-filename=PrimeBooks',
    '--assume-yes-for-downloads',
    '--show-progress',
    '--show-memory',
    '--remove-output',
    '--follow-imports',
]

# ============================================================================
# OS-SPECIFIC SETTINGS - FORCE NO CONSOLE IN PRODUCTION
# ============================================================================
if IS_WINDOWS:
    print(f"\n  🪟 Windows-specific settings...")

    if DEBUG_MODE:
        cmd.extend(['--windows-console-mode=force'])
        print("  🐛 Console window ENABLED (developer mode)")
    else:
        # ✅ CRITICAL: Disable console for end users
        cmd.extend(['--windows-console-mode=disable'])
        print("  ✅ Console window DISABLED (GUI only for end users)")

    if (BASE_DIR / 'icon.ico').exists():
        cmd.extend([f'--windows-icon-from-ico={BASE_DIR / "icon.ico"}'])

    cmd.extend([
        '--windows-company-name=PrimeBooks',
        '--windows-product-name=PrimeBooks Desktop',
        '--windows-file-version=1.0.0.0',
        '--windows-product-version=1.0.0.0',
        '--windows-file-description=PrimeBooks Accounting Software',
    ])

elif IS_MACOS:
    print(f"\n  🍎 macOS-specific settings...")
    cmd.extend([
        '--macos-create-app-bundle',
        '--macos-app-name=PrimeBooks',
        '--macos-app-version=1.0.0',
    ])

    if (BASE_DIR / 'icon.icns').exists():
        cmd.extend([f'--macos-app-icon={BASE_DIR / "icon.icns"}'])

elif IS_LINUX:
    print(f"\n  🐧 Linux-specific settings...")
    if (BASE_DIR / 'icon.png').exists():
        cmd.extend([f'--linux-icon={BASE_DIR / "icon.png"}'])

# ============================================================================
# ENABLE PLUGINS
# ============================================================================
print("\n  🔌 Enabling plugins...")
cmd.extend([
    '--enable-plugin=pyqt6',
])

# ============================================================================
# INCLUDE PACKAGES
# ============================================================================
print("\n  📦 Including packages...")

core_packages = [
    'django',
    'django_tenants',
    'psycopg2',
    'celery',
    'kombu',
    'billiard',
    'PyQt6',
    'cryptography',
    'requests',
]

for pkg in core_packages:
    cmd.append(f'--include-package={pkg}')
    print(f"    • {pkg}")

# Custom apps
print("\n  🏢 Including custom apps...")
cmd.append('--include-package=primebooks')
cmd.append('--include-package=tenancy')
print(f"    • primebooks")
print(f"    • tenancy")

for app in custom_apps:
    if app not in ['primebooks', 'tenancy']:
        cmd.append(f'--include-package={app}')
        print(f"    • {app}")

# Include specific modules
print("\n  📋 Including specific modules...")
critical_modules = [
    'django.core.management',
    'django.core.management.commands',
    'django.db.backends.postgresql',
    'django_tenants.postgresql_backend',
    'django_tenants.management.commands',
    'PyQt6.QtCore',
    'PyQt6.QtWidgets',
    'PyQt6.QtGui',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtPrintSupport',
]

for mod in critical_modules:
    cmd.append(f'--include-module={mod}')

# ✅ EXPLICITLY include critical primebooks modules
print("\n  🎯 Explicitly including critical primebooks modules...")
critical_primebooks = [
    'primebooks.sync',
    'primebooks.sync_dialogs',
    'primebooks.auth',
    'primebooks.postgres_manager',
    'primebooks.schema_loader',
    'primebooks.signals',
]
for mod in critical_primebooks:
    cmd.append(f'--include-module={mod}')
    print(f"    • {mod}")

# Primebooks modules (auto-discovered)
for mod in primebooks_modules:
    if mod not in critical_primebooks:
        cmd.append(f'--include-module={mod}')

# ============================================================================
# INCLUDE DJANGO TEMPLATES
# ============================================================================
print("\n  📄 Including Django form templates...")

try:
    import django

    django_dir = Path(django.__file__).parent

    django_template_dirs = [
        (django_dir / 'forms' / 'templates', 'django/forms/templates'),
        (django_dir / 'contrib' / 'admin' / 'templates', 'django/contrib/admin/templates'),
        (django_dir / 'contrib' / 'auth' / 'templates', 'django/contrib/auth/templates'),
    ]

    for src_path, dst_path in django_template_dirs:
        if src_path.exists():
            cmd.append(f'--include-data-dir={src_path}={dst_path}')
            print(f"    • {dst_path}")
except Exception as e:
    print(f"    ⚠️  Could not include Django templates: {e}")

# ============================================================================
# ✅ INCLUDE SQL DUMP FILES (CRITICAL!)
# ============================================================================
print("\n  🗄️  Including SQL dump files...")

for sql_file in sql_files_required:
    sql_path = BASE_DIR / sql_file
    if sql_path.exists():
        cmd.append(f'--include-data-files={sql_path}={sql_file}')
        print(f"    ✅ {sql_file}")
    else:
        print(f"    ⚠️  Missing: {sql_file}")

# ============================================================================
# INCLUDE DATA DIRECTORIES
# ============================================================================
print("\n  📁 Including data directories...")

data_dirs = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('locale', 'locale'),
    ('primebooks', 'primebooks'),
    ('tenancy', 'tenancy'),
]

# Add app data
for app in custom_apps:
    app_path = BASE_DIR / app
    if app_path.exists():
        for subdir in ['templates', 'static', 'migrations']:
            subdir_path = app_path / subdir
            if subdir_path.exists():
                data_dirs.append((subdir_path, f'{app}/{subdir}'))

for src, dst in data_dirs:
    src_path = BASE_DIR / src if isinstance(src, str) else src
    if src_path.exists():
        cmd.append(f'--include-data-dir={src_path}={dst}')
        print(f"    • {src_path.name} → {dst}")

# Include manage.py
if (BASE_DIR / 'manage.py').exists():
    cmd.append(f'--include-data-files={BASE_DIR / "manage.py"}=manage.py')
    print(f"    • manage.py")

# Include icon files
print("\n  🎨 Including icon files...")
for icon_file in ['icon.png', 'icon.ico', 'icon.icns']:
    icon_path = BASE_DIR / icon_file
    if icon_path.exists():
        cmd.append(f'--include-data-files={icon_path}={icon_file}')
        print(f"    • {icon_file}")

# ============================================================================
# FOLLOW IMPORTS
# ============================================================================
print("\n  🔍 Setting up import tracking...")
for pkg in ['primebooks', 'tenancy', 'django', 'django_tenants'] + custom_apps:
    cmd.append(f'--follow-import-to={pkg}')

# Remove empty strings
cmd = [arg for arg in cmd if arg]

# ============================================================================
# STEP 5: RUN BUILD
# ============================================================================
print("\n" + "=" * 80)
print("🔨 Step 5: Running Nuitka Build...")
print("=" * 80)
print("\n⏱️  First build takes 10-20 minutes (subsequent builds are faster)")
print("💡 Nuitka downloads dependencies and compiles - be patient!\n")

if not DEBUG_MODE:
    print("✨ Building PRODUCTION version:")
    print("   • NO console window")
    print("   • GUI only")
    print("   • Logs saved to files")
    print("")

try:
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print(f"\n❌ BUILD FAILED with return code {result.returncode}")
        sys.exit(1)

    # Find output
    dist_dir = BASE_DIR / 'dist'

    if IS_MACOS:
        exe_path = dist_dir / 'PrimeBooks.app'
        if not exe_path.exists():
            exe_path = dist_dir / 'PrimeBooks'
    else:
        possible_names = [
            'PrimeBooks.exe' if IS_WINDOWS else 'PrimeBooks',
            'PrimeBooks.bin',
        ]
        exe_path = None
        for name in possible_names:
            test_path = dist_dir / name
            if test_path.exists():
                exe_path = test_path
                break

    if exe_path and exe_path.exists():
        if exe_path.is_file():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
        else:
            size_mb = sum(f.stat().st_size for f in exe_path.rglob('*') if f.is_file()) / (1024 * 1024)

        print("\n" + "=" * 80)
        print("✅ BUILD COMPLETE!")
        print("=" * 80)
        print(f"📦 Executable: {exe_path}")
        print(f"💾 Size: {size_mb:.1f} MB")

        if not IS_WINDOWS and exe_path.is_file():
            os.chmod(exe_path, 0o755)
            print("🔒 Made executable")

        print("\n📊 Build Configuration:")
        if DEBUG_MODE:
            print("   🐛 DEBUG MODE - Console visible")
        else:
            print("   ✨ PRODUCTION MODE - No console, GUI only")

        print(f"\n📊 Included:")
        print(f"   • SHARED_APPS: {len(shared_apps)}")
        print(f"   • TENANT_APPS: {len(tenant_apps)}")
        print(f"   • Primebooks modules: {len(primebooks_modules)}")
        print(f"   • Custom apps: {len(custom_apps)}")
        print(f"   • Django form templates: ✓")
        print(f"   • SQL dumps: ✓")

        print(f"\n🚀 Run your app:")
        if IS_WINDOWS:
            print(f"   dist\\PrimeBooks.exe")
        elif IS_MACOS:
            print(f"   open dist/PrimeBooks.app")
        else:
            print(f"   ./dist/PrimeBooks")

        if not DEBUG_MODE:
            print("\n✨ End User Features:")
            print("   ✓ NO console window")
            print("   ✓ Clean GUI experience")
            print("   ✓ Logs in: %LOCALAPPDATA%\\PrimeBooks\\logs (Windows)")
            print("   ✓ Logs in: ~/.local/share/PrimeBooks/logs (Linux/Mac)")

    else:
        print("\n❌ Build completed but executable not found")
        sys.exit(1)

except Exception as e:
    print(f"\n❌ BUILD FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("🎉 PRIMEBOOKS DESKTOP BUILD COMPLETE!")
print("=" * 80)