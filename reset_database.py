#!/usr/bin/env python3
"""
reset_database.py - IMPROVED VERSION
Reset PrimeBooks Desktop database completely
✅ Handles Windows file locks
✅ Force stops PostgreSQL properly
✅ Retries with elevated permissions if needed
"""
import os
import sys
import shutil
import platform
import time
import subprocess
from pathlib import Path


def get_data_directory():
    """Get platform-specific data directory"""
    if platform.system() == 'Windows':
        return Path(os.environ['APPDATA']) / 'PrimeBooks'
    elif platform.system() == 'Darwin':  # macOS
        return Path.home() / 'Library' / 'Application Support' / 'PrimeBooks'
    else:  # Linux
        return Path.home() / '.local' / 'share' / 'PrimeBooks'


def stop_postgresql_properly(data_dir):
    """Properly stop PostgreSQL before deletion"""
    print("Stopping PostgreSQL server...")

    postgres_dir = data_dir / 'postgresql'
    data_subdir = postgres_dir / 'data'
    bin_dir = postgres_dir / 'bin'

    if not bin_dir.exists():
        print("  No PostgreSQL installation found")
        return

    pg_ctl = bin_dir / ('pg_ctl.exe' if platform.system() == 'Windows' else 'pg_ctl')

    if not pg_ctl.exists():
        print("  pg_ctl not found")
        return

    try:
        # Try to stop gracefully first
        result = subprocess.run([
            str(pg_ctl),
            'stop',
            '-D', str(data_subdir),
            '-m', 'immediate',  # Immediate shutdown
            '-t', '10'  # 10 second timeout
        ], capture_output=True, text=True, timeout=15)

        if result.returncode == 0:
            print("  ✅ PostgreSQL stopped gracefully")
        else:
            print(f"  PostgreSQL stop returned code {result.returncode}")

        # Wait for processes to fully terminate
        time.sleep(2)

    except subprocess.TimeoutExpired:
        print("  ⚠️ PostgreSQL stop timed out")
    except Exception as e:
        print(f"  ⚠️ Error stopping PostgreSQL: {e}")


def kill_postgres_processes():
    """Force kill any PostgreSQL processes"""
    print("Force killing PostgreSQL processes...")

    system = platform.system()

    try:
        if system == 'Windows':
            # Kill postgres.exe processes
            subprocess.run(['taskkill', '/F', '/IM', 'postgres.exe'],
                           capture_output=True, timeout=5)
            subprocess.run(['taskkill', '/F', '/IM', 'pg_ctl.exe'],
                           capture_output=True, timeout=5)
            print("  ✅ Killed Windows processes")
        else:
            # Kill postgres processes on Unix
            subprocess.run(['pkill', '-9', 'postgres'],
                           capture_output=True, timeout=5)
            print("  ✅ Killed Unix processes")

        # Wait for processes to fully terminate
        time.sleep(2)

    except Exception as e:
        print(f"  ⚠️ Error killing processes: {e}")


def stop_running_processes():
    """Stop any running PrimeBooks processes"""
    print("Stopping any running PrimeBooks instances...")

    try:
        if platform.system() == 'Windows':
            # Stop Python processes running PrimeBooks
            subprocess.run(['taskkill', '/F', '/IM', 'python.exe', '/FI',
                            'WINDOWTITLE eq PrimeBooks*'],
                           capture_output=True, timeout=5)
            subprocess.run(['taskkill', '/F', '/IM', 'pythonw.exe'],
                           capture_output=True, timeout=5)
        else:
            os.system('pkill -f "main.py" 2>/dev/null')
    except Exception as e:
        print(f"  ⚠️ Error: {e}")


def delete_with_retry(path, max_retries=3):
    """
    Delete directory with retry logic for Windows file locks
    """
    for attempt in range(max_retries):
        try:
            if path.exists():
                # Try to remove read-only attributes on Windows
                if platform.system() == 'Windows':
                    try:
                        subprocess.run(['attrib', '-R', str(path / '*.*'), '/S'],
                                       capture_output=True, timeout=10)
                    except:
                        pass

                shutil.rmtree(path)
                return True

        except PermissionError as e:
            if attempt < max_retries - 1:
                print(f"  ⚠️ Attempt {attempt + 1} failed: {e}")
                print(f"  Retrying in 2 seconds...")
                time.sleep(2)
            else:
                raise
        except Exception as e:
            raise

    return False


def delete_directory_carefully(data_dir):
    """
    Delete directory with proper error handling
    """
    if not data_dir.exists():
        print("✓ No data directory found - nothing to delete")
        return True

    print(f"Deleting {data_dir}...")

    try:
        # First, try to delete everything except PostgreSQL binaries
        items_to_delete = []
        postgres_bin = data_dir / 'postgresql' / 'bin'

        for item in data_dir.iterdir():
            if item == data_dir / 'postgresql':
                # Handle PostgreSQL directory specially
                postgres_dir = data_dir / 'postgresql'
                for pg_item in postgres_dir.iterdir():
                    if pg_item.name != 'bin':
                        items_to_delete.append(pg_item)
            else:
                items_to_delete.append(item)

        # Delete non-binary items first
        for item in items_to_delete:
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                print(f"  ✓ Deleted {item.name}")
            except Exception as e:
                print(f"  ⚠️ Could not delete {item.name}: {e}")

        # Now try to delete the bin directory with retries
        if postgres_bin.exists():
            print(f"  Deleting PostgreSQL binaries...")
            try:
                delete_with_retry(postgres_bin, max_retries=3)
                print(f"  ✓ Deleted PostgreSQL binaries")
            except Exception as e:
                print(f"  ⚠️ Could not delete PostgreSQL binaries: {e}")
                print(f"  You may need to delete manually: {postgres_bin}")

        # Finally, delete the main directory
        try:
            if data_dir.exists():
                delete_with_retry(data_dir, max_retries=3)
            print("✅ Database reset complete!")
            return True
        except Exception as e:
            print(f"⚠️ Partial deletion - some files remain: {e}")
            print(f"Remaining files are at: {data_dir}")
            print(f"You can manually delete them or restart and try again.")
            return False

    except Exception as e:
        print(f"❌ Error deleting directory: {e}")
        return False


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

    # Step 1: Stop PrimeBooks processes
    stop_running_processes()
    time.sleep(1)

    # Step 2: Stop PostgreSQL properly
    stop_postgresql_properly(data_dir)
    time.sleep(1)

    # Step 3: Force kill any remaining PostgreSQL processes
    kill_postgres_processes()
    time.sleep(1)

    # Step 4: Delete the directory
    success = delete_directory_carefully(data_dir)

    print()
    print("=" * 60)
    if success:
        print("Next steps:")
        print("1. Run: python main.py")
        print("2. You'll see the login dialog")
        print("3. Enter your credentials")
        print("4. Data will sync from server")
    else:
        print("Reset partially completed.")
        print("If files remain locked:")
        print("1. Restart your computer")
        print("2. Run this script again")
        print("3. Or manually delete: " + str(data_dir))
    print("=" * 60)


if __name__ == '__main__':
    reset_database()