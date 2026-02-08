#!/usr/bin/env python3
"""
PrimeBooks Desktop - Installer Builder
Builds installers for Windows and Linux
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path


def build_windows_installer():
    """Build Windows installer using Inno Setup"""
    print("=" * 60)
    print("Building Windows Installer")
    print("=" * 60)

    # Check if Inno Setup is installed
    inno_path = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    if not inno_path.exists():
        print("❌ Inno Setup not found!")
        print("   Download from: https://jrsoftware.org/isinfo.php")
        return False

    # Build with Inno Setup
    script = Path("primebooks_installer.iss")
    if not script.exists():
        print(f"❌ Script not found: {script}")
        return False

    print(f"📦 Compiling installer...")
    result = subprocess.run([str(inno_path), str(script)])

    if result.returncode == 0:
        print("✅ Windows installer created!")
        return True
    else:
        print("❌ Build failed!")
        return False


def build_linux_deb():
    """Build .deb package for Ubuntu/Debian"""
    print("=" * 60)
    print("Building Linux .deb Package")
    print("=" * 60)

    package_name = "primebooks-desktop-1.0.0"
    package_dir = Path(package_name)

    # Clean previous build
    if package_dir.exists():
        shutil.rmtree(package_dir)

    # Create directory structure
    dirs = [
        package_dir / "DEBIAN",
        package_dir / "opt" / "primebooks",
        package_dir / "usr" / "share" / "applications",
        package_dir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Create control file
    control = package_dir / "DEBIAN" / "control"
    control.write_text("""Package: primebooks-desktop
Version: 1.0.0
Section: utils
Priority: optional
Architecture: amd64
Depends: libqt6widgets6, libqt6webengine6
Maintainer: PrimeBooks <support@primebooks.sale>
Description: PrimeBooks Desktop Application
 Professional accounting and inventory management software.
""")

    # Create desktop entry
    desktop = package_dir / "usr" / "share" / "applications" / "primebooks.desktop"
    desktop.write_text("""[Desktop Entry]
Version=1.0
Type=Application
Name=PrimeBooks
Comment=Accounting & Inventory Management
Exec=/opt/primebooks/PrimeBooks
Icon=primebooks
Terminal=false
Categories=Office;Finance;
""")

    # Create postinst script
    postinst = package_dir / "DEBIAN" / "postinst"
    postinst.write_text("""#!/bin/bash
set -e
chmod +x /opt/primebooks/PrimeBooks
update-desktop-database /usr/share/applications 2>/dev/null || true
exit 0
""")
    postinst.chmod(0o755)

    # Copy files
    dist_dir = Path("dist")
    if not dist_dir.exists():
        print("❌ dist/ directory not found!")
        return False

    print("📦 Copying files...")
    shutil.copytree(dist_dir, package_dir / "opt" / "primebooks", dirs_exist_ok=True)

    # Copy icon
    icon = Path("icon.png")
    if icon.exists():
        shutil.copy(icon, package_dir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "primebooks.png")

    # Build .deb
    print("📦 Building .deb package...")
    result = subprocess.run(["dpkg-deb", "--build", package_name])

    if result.returncode == 0:
        print(f"✅ Package created: {package_name}.deb")
        return True
    else:
        print("❌ Build failed!")
        return False


def build_appimage():
    """Build AppImage for universal Linux"""
    print("=" * 60)
    print("Building AppImage")
    print("=" * 60)

    # Check if appimage-builder is installed
    try:
        subprocess.run(["appimage-builder", "--version"], capture_output=True)
    except FileNotFoundError:
        print("❌ appimage-builder not found!")
        print("   Install with: pip install appimage-builder")
        return False

    # Build
    result = subprocess.run(["appimage-builder", "--recipe", "AppImageBuilder.yml"])

    if result.returncode == 0:
        print("✅ AppImage created!")
        return True
    else:
        print("❌ Build failed!")
        return False


def main():
    print("\n" + "=" * 60)
    print("PrimeBooks Desktop - Installer Builder")
    print("=" * 60 + "\n")

    # Detect platform
    if sys.platform == "win32":
        success = build_windows_installer()
    elif sys.platform.startswith("linux"):
        print("Choose build type:")
        print("1. .deb package (Ubuntu/Debian)")
        print("2. AppImage (Universal)")
        print("3. Both")

        choice = input("\nChoice (1-3): ").strip()

        if choice == "1":
            success = build_linux_deb()
        elif choice == "2":
            success = build_appimage()
        elif choice == "3":
            success = build_linux_deb() and build_appimage()
        else:
            print("❌ Invalid choice")
            success = False
    else:
        print(f"❌ Unsupported platform: {sys.platform}")
        success = False

    print("\n" + "=" * 60)
    if success:
        print("✅ BUILD SUCCESSFUL!")
    else:
        print("❌ BUILD FAILED!")
    print("=" * 60 + "\n")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())