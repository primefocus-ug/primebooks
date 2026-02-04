#!/usr/bin/env python3
"""
Automatic Settings.py Patcher for Desktop Builds
Makes Celery and other server-only dependencies optional
"""
import re
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / 'tenancy' / 'settings.py'

print("=" * 80)
print("🔧 Patching tenancy/settings.py for Desktop Compatibility")
print("=" * 80)

if not SETTINGS_FILE.exists():
    print(f"❌ Error: {SETTINGS_FILE} not found")
    exit(1)

# Read current settings
content = SETTINGS_FILE.read_text()

# Create backup
backup_file = SETTINGS_FILE.with_suffix('.py.backup')
backup_file.write_text(content)
print(f"✅ Backup created: {backup_file}")

# Check if already patched
if 'try:' in content and 'from celery' in content:
    print("✅ Settings.py already patched for desktop!")
    exit(0)

print("\n📝 Applying patches...")

# ============================================================================
# PATCH 1: Make Celery Import Optional
# ============================================================================
celery_patterns = [
    (r'from celery\.schedules import crontab',
     '''# Desktop-compatible Celery import
try:
    from celery.schedules import crontab
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    crontab = lambda **kwargs: None  # Dummy for desktop mode'''),

    (r'from celery import Celery',
     '''# Desktop-compatible Celery import
try:
    from celery import Celery
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    Celery = None  # Dummy for desktop mode'''),
]

for pattern, replacement in celery_patterns:
    if re.search(pattern, content):
        content = re.sub(pattern, replacement, content)
        print(f"  ✅ Made Celery import optional")
        break

# ============================================================================
# PATCH 2: Wrap CELERY Configuration
# ============================================================================
# Find CELERY_BEAT_SCHEDULE and wrap it
if 'CELERY_BEAT_SCHEDULE' in content:
    lines = content.split('\n')
    new_lines = []
    in_celery_config = False
    indent_level = 0

    for i, line in enumerate(lines):
        # Start of CELERY config
        if re.match(r'^\s*CELERY_', line) and not in_celery_config:
            in_celery_config = True
            indent_level = len(line) - len(line.lstrip())

            # Add conditional wrapper
            if 'CELERY_AVAILABLE' not in '\n'.join(lines[max(0, i - 5):i]):
                new_lines.append('')
                new_lines.append('# Celery configuration (only for web mode)')
                new_lines.append('if CELERY_AVAILABLE:')
            new_lines.append('    ' + line)
            continue

        # Inside CELERY config
        if in_celery_config:
            current_indent = len(line) - len(line.lstrip())

            # End of CELERY config block
            if line.strip() and current_indent <= indent_level and not re.match(r'^\s*CELERY_', line):
                in_celery_config = False
                new_lines.append('else:')
                new_lines.append('    # Desktop mode - no Celery needed')
                new_lines.append('    CELERY_BEAT_SCHEDULE = {}')
                new_lines.append(line)
                continue

            # Add indentation to CELERY lines
            if line.strip():
                new_lines.append('    ' + line)
            else:
                new_lines.append(line)
            continue

        new_lines.append(line)

    # Handle if CELERY config goes to end of file
    if in_celery_config:
        new_lines.append('else:')
        new_lines.append('    CELERY_BEAT_SCHEDULE = {}')

    content = '\n'.join(new_lines)
    print(f"  ✅ Wrapped CELERY configuration in conditional")

# ============================================================================
# PATCH 3: Make Other Optional Dependencies Safe
# ============================================================================
optional_imports = [
    'channels',
    'channels_redis',
    'redis',
]

for module in optional_imports:
    pattern = f'import {module}'
    if pattern in content and f'try:' not in content[:content.index(pattern)]:
        replacement = f'''try:
    import {module}
except ImportError:
    {module} = None  # Optional for desktop mode'''
        content = content.replace(f'import {module}', replacement)
        print(f"  ✅ Made {module} import optional")

# Write patched file
SETTINGS_FILE.write_text(content)

print("\n" + "=" * 80)
print("✅ Settings.py successfully patched!")
print("=" * 80)
print(f"\n💾 Original saved to: {backup_file}")
print(f"✅ Patched file: {SETTINGS_FILE}")
print("\n📝 Changes made:")
print("   • Celery imports are now optional (try/except)")
print("   • Celery config wrapped in 'if CELERY_AVAILABLE'")
print("   • Other optional dependencies made safe")
print("\n💡 Now you can build without Celery errors:")
print("   python3 pyinstaller_comprehensive.py")
print("   or")
print("   python3 nuitka_comprehensive.py")