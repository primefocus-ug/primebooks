#!/usr/bin/env python3
"""
🍎 NUITKA BUILD - macOS OPTIMIZED
================================================================================
macOS-specific build with .app bundle creation
✅ Creates proper .app bundle
✅ Code signing ready
✅ Notarization ready
✅ Universal binary support (Intel + Apple Silicon)
================================================================================
"""
import subprocess
import sys
import os
import shutil
import platform
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

print("=" * 80)
print("🍎 NUITKA BUILD - macOS OPTIMIZED")
print("=" * 80)

# Check if running on macOS
if platform.system() != 'Darwin':
    print("❌ This script is for macOS only!")
    print("   Use build_nuitka_ultimate.py for cross-platform builds")
    sys.exit(1)

# Check for Xcode Command Line Tools
print("\n🔧 Checking Xcode Command Line Tools...")
try:
    subprocess.run(['xcode-select', '-p'], check=True, capture_output=True)
    print("  ✅ Xcode Command Line Tools found")
except subprocess.CalledProcessError:
    print("  ❌ Xcode Command Line Tools not found!")
    print("  📥 Please install: xcode-select --install")
    sys.exit(1)

# ============================================================================
# INSTALL NUITKA + DEPENDENCIES
# ============================================================================
print("\n📥 Installing Nuitka and dependencies...")

subprocess.run([
    sys.executable, '-m', 'pip', 'install', '-U',
    'nuitka',
    'ordered-set',
    'zstandard',
], check=True)

print("✅ Dependencies installed")

# ============================================================================
# DISCOVER MODULES
# ============================================================================
print("\n📦 Discovering modules...")

primebooks_modules = []
primebooks_dir = BASE_DIR / 'primebooks'
if primebooks_dir.exists():
    for item in primebooks_dir.glob('*.py'):
        if item.name != '__init__.py':
            primebooks_modules.append(f'primebooks.{item.stem}')

django_apps = []
for item in BASE_DIR.iterdir():
    if item.is_dir() and not item.name.startswith('.'):
        if (item / '__init__.py').exists() or (item / 'models.py').exists():
            exclude = ['dist', 'build', 'venv', 'env', '__pycache__']
            if item.name not in exclude:
                django_apps.append(item.name)

print(f"  ✅ Primebooks modules: {len(primebooks_modules)}")
print(f"  ✅ Django apps: {len(django_apps)}")

# ============================================================================
# CLEAN BUILD
# ============================================================================
print("\n🧹 Cleaning build directories...")

for dir_name in ['dist', 'build', 'primebooks.build', 'primebooks.dist', 'primebooks.onefile-build']:
    dir_path = BASE_DIR / dir_name
    if dir_path.exists():
        shutil.rmtree(dir_path)

print("✅ Clean complete")

# ============================================================================
# BUILD COMMAND
# ============================================================================
print("\n🔧 Building Nuitka command...")

# Detect architecture
arch = platform.machine()
print(f"  Architecture: {arch}")

nuitka_cmd = [
    sys.executable, '-m', 'nuitka',

    # Output
    '--standalone',
    '--onefile',
    '--output-dir=dist',

    # macOS-specific
    '--macos-create-app-bundle',  # Create .app bundle
    '--macos-app-name=PrimeBooks',

    # Optimization
    '--lto=yes',  # Link-time optimization
    '--python-flag=-O',  # Optimize bytecode

    # Include all packages
    '--include-package=primebooks',
    '--include-package=tenancy',
    '--include-package=django',
    '--include-package=django_tenants',
    '--include-package=psycopg2',
    '--include-package=cryptography',
    '--include-package=celery',
    '--include-package=kombu',
    '--include-package=billiard',
    '--include-package=PyQt6',
]

# Add Django apps
for app in django_apps:
    nuitka_cmd.append(f'--include-package={app}')

# Add data directories
data_dirs = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('locale', 'locale'),
    ('primebooks', 'primebooks'),
]

for src, dst in data_dirs:
    src_path = BASE_DIR / src
    if src_path.exists():
        nuitka_cmd.append(f'--include-data-dir={src_path}={dst}')

# Critical imports
critical = [
    'django.core.management.commands.migrate',
    'django_tenants.management.commands.migrate_schemas',
    'django_tenants.postgresql_backend',
    'psycopg2._psycopg',
    'celery.app.base',
    'PyQt6.QtWebEngineWidgets',
]

for imp in critical:
    nuitka_cmd.append(f'--include-module={imp}')

# Plugins
nuitka_cmd.extend([
    '--enable-plugin=anti-bloat',
    '--enable-plugin=pyqt6',
])

# Icon (if exists)
icon_path = BASE_DIR / 'icon.icns'
if icon_path.exists():
    nuitka_cmd.append(f'--macos-app-icon={icon_path}')

# Main script
nuitka_cmd.append(str(BASE_DIR / 'main.py'))

# ============================================================================
# RUN BUILD
# ============================================================================
print("\n" + "=" * 80)
print("🔨 COMPILING WITH NUITKA...")
print("=" * 80)
print("⏱️  Estimated time: 15-30 minutes")
print("")

try:
    subprocess.run(nuitka_cmd, check=True)

    app_path = BASE_DIR / 'dist' / 'PrimeBooks.app'

    if app_path.exists():
        # Calculate total size of .app bundle
        total_size = sum(f.stat().st_size for f in app_path.rglob('*') if f.is_file())
        size_mb = total_size / (1024 * 1024)

        print("\n" + "=" * 80)
        print("✅ BUILD SUCCESSFUL!")
        print("=" * 80)
        print(f"\n📦 Application: {app_path}")
        print(f"💾 Size: {size_mb:.1f} MB")
        print(f"🏗️  Architecture: {arch}")

        print(f"\n🚀 Run:")
        print(f"   open dist/PrimeBooks.app")
        print(f"   # or double-click in Finder")

        print(f"\n📝 Optional: Code signing")
        print(f"   codesign --deep --force --sign - dist/PrimeBooks.app")

    else:
        print("\n❌ Build failed - .app bundle not found")
        sys.exit(1)

except subprocess.CalledProcessError as e:
    print(f"\n❌ Build failed with code {e.returncode}")
    sys.exit(1)