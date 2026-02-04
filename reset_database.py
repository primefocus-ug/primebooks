#!/usr/bin/env python3
"""
reset_database.py
Reset PrimeBooks Desktop database completely
"""
import os
import sys
import shutil
import platform
from pathlib import Path


def get_data_directory():
    """Get platform-specific data directory"""
    if platform.system() == 'Windows':
        return Path(os.environ['APPDATA']) / 'PrimeBooks'
    elif platform.system() == 'Darwin':  # macOS
        return Path.home() / 'Library' / 'Application Support' / 'PrimeBooks'
    else:  # Linux
        return Path.home() / '.local' / 'share' / 'PrimeBooks'


def stop_running_processes():
    """Stop any running PrimeBooks processes"""
    print("Stopping any running instances...")

    try:
        if platform.system() == 'Windows':
            os.system('taskkill /F /IM python.exe /FI "WINDOWTITLE eq PrimeBooks*" 2>nul')
        else:
            os.system('pkill -f "main.py" 2>/dev/null')
            os.system('pkill -f "postgres" 2>/dev/null')
    except:
        pass


def reset_database():
    """Reset the database"""
    print("=" * 60)
    print("PrimeBooks Desktop - Database Reset")
    print("=" * 60)
    print()

    # Get data directory
    data_dir = get_data_directory()

    print(f"Data directory: {data_dir}")
    print()

    # Confirm
    print("⚠️  WARNING: This will delete ALL local data!")
    print()
    response = input("Are you sure you want to continue? (yes/no): ")

    if response.lower() != 'yes':
        print("Cancelled.")
        return

    print()

    # Stop processes
    stop_running_processes()

    # Delete data directory
    if data_dir.exists():
        print(f"Deleting {data_dir}...")
        try:
            shutil.rmtree(data_dir)
            print("✅ Database reset complete!")
        except Exception as e:
            print(f"❌ Error deleting directory: {e}")
            return
    else:
        print("✓ No data directory found - nothing to delete")

    print()
    print("=" * 60)
    print("Next steps:")
    print("1. Run: python main.py")
    print("2. You'll see the login dialog")
    print("3. Enter your credentials")
    print("4. Data will sync from server")
    print("=" * 60)


if __name__ == '__main__':
    reset_database()