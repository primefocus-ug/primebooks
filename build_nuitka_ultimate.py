#!/usr/bin/env python3
"""
🚀 ULTIMATE NUITKA BUILD SCRIPT - ALL PLATFORMS
================================================================================
Compiles PrimeBooks to native C code with EVERYTHING included
✅ Windows (EXE)
✅ macOS (APP bundle)
✅ Linux (Binary)
✅ ZERO packages excluded - Full functionality guaranteed
✅ Optimized C compilation for performance
================================================================================
"""
import subprocess
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
print(f"🚀 NUITKA ULTIMATE BUILD - {OS_NAME}")
print("=" * 80)
print("📌 Philosophy: INCLUDE EVERYTHING - Size doesn't matter, FUNCTIONALITY does")
print("⚡ Compiling Python → C → Native Binary")
print("=" * 80)

# ============================================================================
# STEP 0: CHECK NUITKA INSTALLATION
# ============================================================================
print("\n🔍 Step 0: Checking Nuitka installation...")

try:
    result = subprocess.run(['python', '-m', 'nuitka', '--version'],
                            capture_output=True, text=True, check=True)
    print(f"  ✅ Nuitka version: {result.stdout.strip()}")
except subprocess.CalledProcessError:
    print("  ❌ Nuitka not found!")
    print("  📥 Installing Nuitka...")
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', 'nuitka', 'ordered-set', 'zstandard'], check=True)
    print("  ✅ Nuitka installed successfully")

# Check for C compiler
print("\n🔧 Checking C compiler...")
if IS_WINDOWS:
    print("  ℹ️  Windows: Nuitka will download MinGW64 automatically if needed")
elif IS_MACOS:
    print("  ℹ️  macOS: Ensure Xcode Command Line Tools are installed")
    print("     Run: xcode-select --install")
elif IS_LINUX:
    print("  ℹ️  Linux: Ensure gcc/g++ are installed")
    print("     Run: sudo apt-get install gcc g++ ccache")

# ============================================================================
# STEP 1: DISCOVER ALL MODULES
# ============================================================================
print("\n📦 Step 1: Discovering ALL modules and packages...")

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
    print(f"\n  📂 Scanning primebooks directory...")
    for item in primebooks_dir.glob('*.py'):
        if item.name != '__init__.py':
            module_name = f'primebooks.{item.stem}'
            primebooks_modules.append(module_name)
            print(f"     • {module_name}")

    # Verify postgres_manager
    if (primebooks_dir / 'postgres_manager.py').exists():
        print(f"     ✅ primebooks.postgres_manager found")
else:
    print(f"  ⚠️  WARNING: primebooks directory not found")

print(f"\n  Total primebooks modules: {len(primebooks_modules)}")

# Django apps
django_apps = []
print(f"\n  📂 Scanning Django apps...")
for item in BASE_DIR.iterdir():
    if item.is_dir() and not item.name.startswith('.'):
        if (item / '__init__.py').exists() or (item / 'models.py').exists():
            exclude = ['dist', 'build', 'venv', 'env', '__pycache__',
                       'staticfiles', 'media', 'logs', '.git', '.venv',
                       'primebooks.build', 'primebooks.dist', 'primebooks.onefile-build']
            if item.name not in exclude:
                django_apps.append(item.name)
                print(f"     • {item.name}")

print(f"\n  Total Django apps: {len(django_apps)}")

# Read requirements.txt
requirements = []
requirements_file = BASE_DIR / 'requirements.txt'
if requirements_file.exists():
    print(f"\n  📋 Reading requirements.txt...")
    with open(requirements_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                package = line.split('==')[0].split('>=')[0].split('[')[0].strip()
                requirements.append(package)
    print(f"     ✅ Found {len(requirements)} packages")

# ============================================================================
# STEP 2: CLEAN BUILD
# ============================================================================
print("\n🧹 Step 2: Cleaning previous builds...")

clean_dirs = ['dist', 'build', 'primebooks.build', 'primebooks.dist',
              'primebooks.onefile-build', '__pycache__']
for dir_name in clean_dirs:
    dir_path = BASE_DIR / dir_name
    if dir_path.exists():
        shutil.rmtree(dir_path)
        print(f"  ✅ Removed {dir_name}/")

# Remove .bin and .pyi files
for pattern in ['*.bin', '*.pyi']:
    for file in BASE_DIR.glob(pattern):
        file.unlink()
        print(f"  ✅ Removed {file.name}")

# ============================================================================
# STEP 3: BUILD NUITKA COMMAND
# ============================================================================
print("\n🔧 Step 3: Building Nuitka command - INCLUDE EVERYTHING...")

nuitka_args = [
    sys.executable,
    '-m', 'nuitka',

    # ========================================================================
    # OUTPUT OPTIONS
    # ========================================================================
    '--standalone',  # Create standalone distribution
    '--onefile',  # Single executable file
    f'--output-dir={BASE_DIR / "dist"}',
    '--output-filename=PrimeBooks',

    # ========================================================================
    # COMPILATION OPTIONS
    # ========================================================================
    '--assume-yes-for-downloads',  # Auto-download dependencies
    '--warn-implicit-exceptions',  # Warn about exception handling
    '--warn-unusual-code',  # Warn about unusual code patterns
    '--lto=yes',  # Link Time Optimization (faster exe)

    # Python flags
    '--python-flag=no_site',  # Don't import site on startup
    '--python-flag=-O',  # Optimize (remove asserts)

    # ========================================================================
    # INCLUDE EVERYTHING - LOCAL PACKAGES
    # ========================================================================
    '--include-package=primebooks',
    '--include-package=tenancy',
]

# Include all Django apps
print("\n  📦 Including Django apps as full packages:")
for app in django_apps:
    nuitka_args.append(f'--include-package={app}')
    print(f"     • {app}")

# ========================================================================
# INCLUDE EVERYTHING - THIRD-PARTY PACKAGES
# ========================================================================
print("\n  📦 Including third-party packages (FULL PACKAGES):")

# Critical packages that need FULL inclusion
critical_packages = [
    'django',
    'django_tenants',
    'psycopg2',
    'cryptography',
    'celery',
    'kombu',
    'billiard',
    'amqp',
    'vine',
    'PyQt6',
]

for pkg in critical_packages:
    nuitka_args.append(f'--include-package={pkg}')
    print(f"     • {pkg}")

# Include ALL packages from requirements.txt
print("\n  📦 Including ALL packages from requirements.txt:")
for req in requirements:
    # Convert package name to module name
    module_name = req.replace('-', '_').lower()

    # Skip duplicates
    if module_name not in [p.lower() for p in critical_packages]:
        nuitka_args.append(f'--include-package={module_name}')
        print(f"     • {module_name}")

# ========================================================================
# EXPLICIT MODULE IMPORTS (for dynamic imports)
# ========================================================================
print("\n  🎯 Adding explicit imports for dynamic modules:")

explicit_imports = [
    # Django core
    'django.core.management',
    'django.core.management.commands',
    'django.core.management.commands.migrate',
    'django.core.management.commands.makemigrations',
    'django.db.backends.postgresql',

    # django-tenants management
    'django_tenants.management',
    'django_tenants.management.commands',
    'django_tenants.management.commands.migrate_schemas',
    'django_tenants.management.commands.create_tenant',
    'django_tenants.management.commands.create_superuser_schemas',

    # django-tenants backend
    'django_tenants.postgresql_backend',
    'django_tenants.postgresql_backend.base',

    # psycopg2
    'psycopg2._psycopg',
    'psycopg2.extensions',

    # Celery
    'celery.app.base',
    'celery.app.task',
    'celery.worker',
    'celery.worker.request',
    'celery.exceptions',
    'celery.local',
    'celery.utils.log',
    'celery.backends',
    'celery.backends.database',

    # PyQt6
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.sip',
]

for imp in explicit_imports:
    nuitka_args.append(f'--include-module={imp}')
    print(f"     • {imp}")

# ========================================================================
# INCLUDE DATA FILES
# ========================================================================
print("\n  📁 Including data files:")

data_inclusions = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('locale', 'locale'),
    ('primebooks', 'primebooks'),  # CRITICAL: Include entire primebooks dir
]

# Add Django app templates
for app in django_apps:
    app_templates = BASE_DIR / app / 'templates'
    if app_templates.exists():
        data_inclusions.append((app_templates, f'{app}/templates'))

for src, dst in data_inclusions:
    src_path = BASE_DIR / src if isinstance(src, str) else src
    if src_path.exists():
        nuitka_args.append(f'--include-data-dir={src_path}={dst}')
        print(f"     • {src_path.name} → {dst}")

# ========================================================================
# PLATFORM-SPECIFIC OPTIONS
# ========================================================================
print("\n  🖥️  Platform-specific options:")

if IS_WINDOWS:
    nuitka_args.extend([
        '--windows-console-mode=disable',  # No console window
        '--windows-icon-from-ico=icon.ico' if (BASE_DIR / 'icon.ico').exists() else None,
        '--mingw64',  # Use MinGW64 compiler
    ])
    print("     • Windows: GUI mode (no console)")
    print("     • Compiler: MinGW64")

elif IS_MACOS:
    nuitka_args.extend([
        '--macos-create-app-bundle',  # Create .app bundle
        '--macos-app-icon=icon.icns' if (BASE_DIR / 'icon.icns').exists() else None,
    ])
    print("     • macOS: Creating .app bundle")

elif IS_LINUX:
    nuitka_args.extend([
        '--linux-icon=icon.png' if (BASE_DIR / 'icon.png').exists() else None,
    ])
    print("     • Linux: Standard binary")

# Remove None values
nuitka_args = [arg for arg in nuitka_args if arg is not None]

# ========================================================================
# PLUGIN OPTIONS (for special packages)
# ========================================================================
print("\n  🔌 Enabling plugins:")

plugins = [
    'anti-bloat',  # Remove unnecessary imports
    'pyqt6',  # PyQt6 support
]

for plugin in plugins:
    nuitka_args.append(f'--enable-plugin={plugin}')
    print(f"     • {plugin}")

# Add main.py at the end
nuitka_args.append(str(BASE_DIR / 'main.py'))

# ============================================================================
# STEP 4: RUN NUITKA BUILD
# ============================================================================
print("\n" + "=" * 80)
print("🔨 Step 4: Running Nuitka compilation...")
print("=" * 80)
print("⏱️  This may take 10-30 minutes depending on your system")
print("⚡ Nuitka is compiling Python → C → Native code...")
print("")

try:
    # Print command for debugging
    print("📋 Full Nuitka command:")
    print("   " + " \\\n      ".join(nuitka_args[:5]))
    print("   ... (+ {} more arguments)".format(len(nuitka_args) - 5))
    print("")

    # Run Nuitka
    result = subprocess.run(nuitka_args, check=True)

    # ========================================================================
    # STEP 5: VERIFY BUILD
    # ========================================================================
    print("\n" + "=" * 80)
    print("✅ COMPILATION COMPLETE!")
    print("=" * 80)

    # Find executable
    dist_dir = BASE_DIR / 'dist'

    if IS_WINDOWS:
        exe_path = dist_dir / 'PrimeBooks.exe'
    elif IS_MACOS:
        exe_path = dist_dir / 'PrimeBooks.app'
    else:
        exe_path = dist_dir / 'PrimeBooks'

    if exe_path.exists():
        if exe_path.is_file():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
        else:
            # For .app bundles, get total size
            total_size = sum(f.stat().st_size for f in exe_path.rglob('*') if f.is_file())
            size_mb = total_size / (1024 * 1024)

        print(f"\n📦 Executable: {exe_path}")
        print(f"💾 Size: {size_mb:.1f} MB")

        # Make executable on Unix
        if not IS_WINDOWS and exe_path.is_file():
            os.chmod(exe_path, 0o755)
            print("🔒 Made executable")

        print(f"\n📊 Build Summary:")
        print(f"   • Primebooks modules: {len(primebooks_modules)}")
        print(f"   • Django apps: {len(django_apps)}")
        print(f"   • Third-party packages: {len(requirements)}")
        print(f"   • Platform: {OS_NAME}")
        print(f"   • Type: Native C-compiled binary")

        print(f"\n🚀 To run:")
        if IS_WINDOWS:
            print(f"   dist\\PrimeBooks.exe")
        elif IS_MACOS:
            print(f"   open dist/PrimeBooks.app")
        else:
            print(f"   ./dist/PrimeBooks")

        print("\n" + "=" * 80)
        print("🎉 NUITKA BUILD SUCCESSFUL!")
        print("=" * 80)
        print("\n💡 Your app is now compiled to native C code!")
        print("   ⚡ Faster startup")
        print("   🔒 Code protection (harder to reverse engineer)")
        print("   📦 Single binary distribution")

    else:
        print("\n❌ Build completed but executable not found")
        print(f"   Expected: {exe_path}")
        print(f"   Check: {dist_dir}")
        sys.exit(1)

except subprocess.CalledProcessError as e:
    print("\n" + "=" * 80)
    print("❌ NUITKA BUILD FAILED!")
    print("=" * 80)
    print(f"\nError code: {e.returncode}")
    print("\n💡 Common issues:")
    print("   • Missing C compiler (install gcc/clang/MinGW)")
    print("   • Insufficient memory (Nuitka needs ~2GB RAM)")
    print("   • Conflicting package versions")
    print("\n📋 Check the output above for specific errors")
    sys.exit(1)

except Exception as e:
    print(f"\n❌ UNEXPECTED ERROR: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)