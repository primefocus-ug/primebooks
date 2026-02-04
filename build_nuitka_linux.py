#!/usr/bin/env python3
"""
🐧 NUITKA BUILD - LINUX OPTIMIZED
================================================================================
Linux-specific build with maximum compatibility
✅ Uses system GCC/G++
✅ Static linking where possible
✅ Compatible with most Linux distributions
✅ AppImage creation support
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
print("🐧 NUITKA BUILD - LINUX OPTIMIZED")
print("=" * 80)

# Check if running on Linux
if platform.system() != 'Linux':
    print("❌ This script is for Linux only!")
    print("   Use build_nuitka_ultimate.py for cross-platform builds")
    sys.exit(1)

# Check for required build tools
print("\n🔧 Checking build dependencies...")

required_tools = {
    'gcc': 'GCC compiler',
    'g++': 'G++ compiler',
    'make': 'Make build tool',
}

missing = []
for tool, description in required_tools.items():
    if shutil.which(tool) is None:
        missing.append(f"{tool} ({description})")
        print(f"  ❌ {description} not found")
    else:
        result = subprocess.run([tool, '--version'], capture_output=True, text=True)
        version = result.stdout.split('\n')[0]
        print(f"  ✅ {description}: {version}")

if missing:
    print("\n⚠️  Missing dependencies:")
    for item in missing:
        print(f"  • {item}")
    print("\n📥 Install with:")
    print("  sudo apt-get install gcc g++ make ccache  # Debian/Ubuntu")
    print("  sudo yum install gcc gcc-c++ make ccache  # RHEL/CentOS")
    print("  sudo dnf install gcc gcc-c++ make ccache  # Fedora")
    print("  sudo pacman -S gcc make ccache            # Arch Linux")

    response = input("\n❓ Continue anyway? (y/N): ")
    if response.lower() != 'y':
        sys.exit(1)

# Check for ccache (speeds up compilation)
if shutil.which('ccache'):
    print("  ✅ ccache found (compilation will be faster)")
else:
    print("  ℹ️  ccache not found (optional, but speeds up builds)")

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

# Detect Linux distribution
try:
    with open('/etc/os-release', 'r') as f:
        os_info = dict(line.strip().split('=', 1) for line in f if '=' in line)
        distro = os_info.get('PRETTY_NAME', 'Unknown').strip('"')
        print(f"  Distribution: {distro}")
except:
    print("  Distribution: Unknown")

nuitka_cmd = [
    sys.executable, '-m', 'nuitka',

    # Output
    '--standalone',
    '--onefile',
    '--output-dir=dist',
    '--output-filename=PrimeBooks',

    # Linux-specific
    '--linux-onefile-icon=icon.png' if (BASE_DIR / 'icon.png').exists() else None,

    # Optimization
    '--lto=yes',  # Link-time optimization
    '--python-flag=-O',  # Optimize bytecode
    '--assume-yes-for-downloads',  # Auto-download dependencies

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

# Remove None values
nuitka_cmd = [arg for arg in nuitka_cmd if arg is not None]

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

    exe_path = BASE_DIR / 'dist' / 'PrimeBooks'

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)

        # Make executable
        os.chmod(exe_path, 0o755)

        print("\n" + "=" * 80)
        print("✅ BUILD SUCCESSFUL!")
        print("=" * 80)
        print(f"\n📦 Executable: {exe_path}")
        print(f"💾 Size: {size_mb:.1f} MB")

        print(f"\n🚀 Run:")
        print(f"   ./dist/PrimeBooks")

        print(f"\n📝 Optional: Create AppImage")
        print(f"   # For better cross-distro compatibility")
        print(f"   # See: https://appimage.org/")

    else:
        print("\n❌ Build failed - executable not found")
        sys.exit(1)

except subprocess.CalledProcessError as e:
    print(f"\n❌ Build failed with code {e.returncode}")
    print("\n💡 Common issues:")
    print("  • Missing C compiler (install gcc/g++)")
    print("  • Insufficient memory (Nuitka needs ~2GB RAM)")
    print("  • Missing development headers (install python3-dev)")
    sys.exit(1)