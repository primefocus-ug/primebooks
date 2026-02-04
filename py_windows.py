#!/usr/bin/env python3
"""
CROSS-PLATFORM PyInstaller Build Script for PrimeBooks Desktop
✅ Auto-detects OS (Windows, macOS, Linux)
✅ Uses virtual environment packages
✅ Includes ALL modules
✅ Production-ready
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
print(f"🚀 PrimeBooks Desktop Build - {OS_NAME}")
print("=" * 80)

# ============================================================================
# STEP 1: DETECT VIRTUAL ENVIRONMENT
# ============================================================================
print("\n🔍 Step 1: Detecting virtual environment...")

# Check if running in virtual environment
in_venv = (hasattr(sys, 'real_prefix') or
           (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

if in_venv:
    venv_path = Path(sys.prefix)
    print(f"  ✅ Running in virtual environment: {venv_path}")
else:
    print(f"  ⚠️  Not in virtual environment")
    print(f"     Using system Python: {sys.prefix}")

# Get site-packages path
if IS_WINDOWS:
    site_packages = Path(sys.prefix) / 'Lib' / 'site-packages'
else:
    python_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = Path(sys.prefix) / 'lib' / python_ver / 'site-packages'

print(f"  📦 Site packages: {site_packages}")

# ============================================================================
# STEP 2: VERIFY STRUCTURE
# ============================================================================
print("\n🔍 Step 2: Verifying project structure...")

# Check critical files
critical_files = {
    'main.py': 'Entry point',
    'tenancy/settings.py': 'Django settings',
    'primebooks/__init__.py': 'Primebooks package',
}

all_exist = True
for file_path, desc in critical_files.items():
    full_path = BASE_DIR / file_path
    if full_path.exists():
        print(f"  ✅ {desc}: {file_path}")
    else:
        print(f"  ❌ MISSING {desc}: {file_path}")
        all_exist = False

if not all_exist:
    print("\n❌ Critical files missing!")
    sys.exit(1)

# ============================================================================
# STEP 3: DISCOVER MODULES
# ============================================================================
print("\n📦 Step 3: Discovering modules...")

# Primebooks modules
primebooks_dir = BASE_DIR / 'primebooks'
primebooks_modules = []
if primebooks_dir.exists():
    for item in primebooks_dir.glob('*.py'):
        if item.name != '__init__.py':
            module_name = f'primebooks.{item.stem}'
            primebooks_modules.append(module_name)
            print(f"  • {module_name}")
print(f"  Total primebooks modules: {len(primebooks_modules)}")

# Django apps
django_apps = []
for item in BASE_DIR.iterdir():
    if item.is_dir() and not item.name.startswith('.'):
        if (item / '__init__.py').exists() or (item / 'models.py').exists():
            exclude_dirs = ['dist', 'build', 'venv', 'env', '__pycache__',
                            'staticfiles', 'media', 'logs', '.git', '.venv']
            if item.name not in exclude_dirs:
                django_apps.append(item.name)
                print(f"  • {item.name}")
print(f"  Total Django apps: {len(django_apps)}")

# ============================================================================
# STEP 4: CLEAN PREVIOUS BUILD
# ============================================================================
print("\n🧹 Step 4: Cleaning previous builds...")

for dir_name in ['dist', 'build']:
    dir_path = BASE_DIR / dir_name
    if dir_path.exists():
        shutil.rmtree(dir_path)
        print(f"  Removed {dir_name}/")

for spec_file in BASE_DIR.glob('*.spec'):
    spec_file.unlink()
    print(f"  Removed {spec_file.name}")

# ============================================================================
# STEP 5: BUILD PYINSTALLER ARGUMENTS
# ============================================================================
print("\n🔧 Step 5: Building PyInstaller arguments...")

# Determine executable name based on OS
if IS_WINDOWS:
    exe_name = 'PrimeBooks.exe'
elif IS_MACOS:
    exe_name = 'PrimeBooks.app'
else:
    exe_name = 'PrimeBooks'

args = [
    str(BASE_DIR / 'main.py'),
    '--name=PrimeBooks',
    '--onefile',

    # Add project paths
    f'--paths={BASE_DIR}',
    f'--paths={BASE_DIR / "tenancy"}',
    f'--paths={BASE_DIR / "primebooks"}',
    f'--paths={site_packages}',  # Include venv packages
]

print(f"\n  Executable: {exe_name}")
print(f"  Paths added:")
print(f"    • {BASE_DIR}")
print(f"    • {site_packages}")

# Tenancy modules
tenancy_modules = [
    'tenancy',
    'tenancy.settings',
    'tenancy.urls',
    'tenancy.wsgi',
    'tenancy.middleware',
]

print("\n  Tenancy modules:")
for module in tenancy_modules:
    args.append(f'--hidden-import={module}')
    print(f"    • {module}")

# Primebooks modules (EXPLICIT)
print("\n  Primebooks modules:")
args.append('--hidden-import=primebooks')
for module in primebooks_modules:
    args.append(f'--hidden-import={module}')
    print(f"    • {module}")

# Django apps with submodules
print("\n  Django apps:")
for app in django_apps:
    args.append(f'--hidden-import={app}')
    print(f"    • {app}")

    # Add common submodules
    app_path = BASE_DIR / app
    for submodule in ['models', 'views', 'urls', 'admin', 'signals', 'tasks',
                      'forms', 'serializers', 'middleware']:
        if (app_path / f'{submodule}.py').exists():
            args.append(f'--hidden-import={app}.{submodule}')

# Requirements.txt packages
print("\n  Packages from requirements.txt:")
requirements_file = BASE_DIR / 'requirements.txt'
packages_added = 0

if requirements_file.exists():
    with open(requirements_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                package = line.split('==')[0].split('>=')[0].split('[')[0].strip()

                # Skip celery (not needed for desktop)
                if package.lower() in ['celery', 'kombu', 'billiard', 'amqp', 'vine']:
                    continue

                module = package.replace('-', '_').lower()
                args.append(f'--hidden-import={module}')
                packages_added += 1

    print(f"    ✅ Added {packages_added} packages (excluded celery)")

# Django core
django_core = [
    'django',
    'django.core',
    'django.core.management',
    'django.core.management.commands',
    'django.db',
    'django.db.backends',
    'django.db.backends.postgresql',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    'django.contrib.humanize',
]

print("\n  Django core:")
for pkg in django_core:
    args.append(f'--hidden-import={pkg}')
    print(f"    • {pkg}")

# Django tenants
django_tenants_modules = [
    'django_tenants',
    'django_tenants.utils',
    'django_tenants.postgresql_backend',
    'django_tenants.management',
    'django_tenants.management.commands',
    'django_tenants.management.commands.migrate_schemas',
    'django_tenants.routers',
]

print("\n  Django tenants:")
for pkg in django_tenants_modules:
    args.append(f'--hidden-import={pkg}')
    print(f"    • {pkg}")

# Essential packages
essential = [
    # Database
    'psycopg2',
    'psycopg2._psycopg',
    'psycopg2.extensions',

    # Cryptography
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.backends',

    # PyQt6
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtWidgets',
    'PyQt6.QtGui',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineCore',

    # Other
    'requests',
    'dotenv',
    'pathlib',
]

print("\n  Essential packages:")
for pkg in essential:
    args.append(f'--hidden-import={pkg}')
    print(f"    • {pkg}")

# Data directories
data_dirs = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('locale', 'locale'),
]

print("\n  Data directories:")
for src, dst in data_dirs:
    src_path = BASE_DIR / src
    if src_path.exists():
        # Use proper separator for OS
        if IS_WINDOWS:
            args.append(f'--add-data={src_path};{dst}')
        else:
            args.append(f'--add-data={src_path}:{dst}')
        print(f"    • {src} → {dst}")

# Exclude unnecessary packages
exclude_modules = [
    'celery',
    'kombu',
    'billiard',
    'amqp',
    'vine',
    'pytest',
    'coverage',
    'black',
    'flake8',
    'pylint',
]

print("\n  Excluding (not needed):")
for mod in exclude_modules:
    args.append(f'--exclude-module={mod}')
    print(f"    • {mod}")

# OS-specific options
if IS_WINDOWS:
    print("\n  Windows-specific options:")
    # Add Windows icon if exists
    icon_path = BASE_DIR / 'static' / 'images' / 'icon.ico'
    if icon_path.exists():
        args.append(f'--icon={icon_path}')
        print(f"    • Icon: {icon_path}")

    # Console window (change to --noconsole for production)
    # args.append('--noconsole')
    print(f"    • Console: Enabled (for debugging)")

elif IS_MACOS:
    print("\n  macOS-specific options:")
    # Add macOS icon if exists
    icon_path = BASE_DIR / 'static' / 'images' / 'icon.icns'
    if icon_path.exists():
        args.append(f'--icon={icon_path}')
        print(f"    • Icon: {icon_path}")

else:  # Linux
    print("\n  Linux-specific options:")
    print(f"    • Standard Linux build")

# Build options
args.extend([
    '--clean',
    '--noconfirm',
    '--log-level=INFO',
])

# ============================================================================
# STEP 6: RUN PYINSTALLER
# ============================================================================
print("\n" + "=" * 80)
print("🔨 Step 6: Running PyInstaller...")
print("=" * 80)
print(f"\n⏳ Building for {OS_NAME}...")
print(f"   This will take 10-15 minutes...\n")

try:
    PyInstaller.__main__.run(args)

    # Find executable
    dist_dir = BASE_DIR / 'dist'
    exe_path = dist_dir / exe_name

    # On Windows, it's PrimeBooks.exe
    if IS_WINDOWS and not exe_path.exists():
        exe_path = dist_dir / 'PrimeBooks.exe'

    # On Linux, just PrimeBooks
    if IS_LINUX and not exe_path.exists():
        exe_path = dist_dir / 'PrimeBooks'

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)

        print("\n" + "=" * 80)
        print("✅ BUILD COMPLETE!")
        print("=" * 80)
        print(f"\n📦 Executable Details:")
        print(f"   OS: {OS_NAME}")
        print(f"   Location: {exe_path}")
        print(f"   Size: {size_mb:.1f} MB")

        # Make executable on Unix-like systems
        if not IS_WINDOWS:
            os.chmod(exe_path, 0o755)
            print(f"   Permissions: ✅ Executable")

        print(f"\n📊 Build Statistics:")
        print(f"   • Primebooks modules: {len(primebooks_modules)}")
        print(f"   • Django apps: {len(django_apps)}")
        print(f"   • Packages: {packages_added}")

        print(f"\n🚀 To run:")
        if IS_WINDOWS:
            print(f"   cd dist")
            print(f"   .\\PrimeBooks.exe")
        else:
            print(f"   cd dist")
            print(f"   ./PrimeBooks")

        print(f"\n✅ Production mode will auto-detect when running compiled exe")
        print(f"   • sys.frozen will be True")
        print(f"   • DEBUG will be False")
        print(f"   • Base domain: primebooks.sale")

    else:
        print("\n❌ Build failed - executable not found")
        print(f"   Expected: {exe_path}")
        sys.exit(1)

except Exception as e:
    print(f"\n❌ BUILD FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("🎉 Build completed successfully!")
print("=" * 80)