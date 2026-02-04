# build_desktop.py
"""
Build script for PrimeBooks Desktop using Nuitka
✅ Compiles to native C code
✅ Creates platform-specific installers
✅ Includes all dependencies
✅ Obfuscates code
"""
import os
import sys
import platform
import subprocess
from pathlib import Path

# Build configuration
APP_NAME = "PrimeBooks"
APP_VERSION = "1.0.0"
APP_AUTHOR = "PrimeBooks Team"
ICON_FILE = "static/images/logo.ico"  # Update with your icon path

# Nuitka options
NUITKA_OPTIONS = [
    # Basic options
    "--standalone",  # Create standalone executable
    "--onefile",  # Single executable file

    # Optimization
    "--lto=yes",  # Link Time Optimization
    "--prefer-source-code",  # Use source code when possible

    # Python options
    f"--python-flag=no_site",  # Don't import site module

    # Output
    f"--output-dir=dist",

    # Windows specific
    "--windows-disable-console",  # No console window on Windows
    f"--windows-icon-from-ico={ICON_FILE}",
    f"--windows-company-name={APP_AUTHOR}",
    f"--windows-product-name={APP_NAME}",
    f"--windows-file-version={APP_VERSION}",
    f"--windows-product-version={APP_VERSION}",

    # Include data files
    "--include-data-dir=static=static",
    "--include-data-dir=templates=templates",

    # Include packages
    "--include-package=django",
    "--include-package=django_tenants",
    "--include-package=rest_framework",
    "--include-package=PyQt6",
    "--include-package=cryptography",
    "--include-package=psycopg2",

    # Follow imports
    "--follow-imports",

    # Remove output
    "--remove-output",  # Remove build folder after build

    # Show progress
    "--show-progress",
    "--show-memory",
]


def build_windows():
    """Build for Windows (.exe)"""
    print("=" * 60)
    print("🪟 BUILDING FOR WINDOWS")
    print("=" * 60)

    options = NUITKA_OPTIONS.copy()
    options.extend([
        "--windows-disable-console",
        "--windows-icon-from-ico=static/images/logo.ico",
    ])

    # Build command
    cmd = ["python", "-m", "nuitka"] + options + ["main.py"]

    print("\nRunning Nuitka...")
    print(" ".join(cmd))

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n✅ Windows build successful!")
        print(f"Output: dist/main.exe")

        # Create installer using NSIS
        create_windows_installer()
    else:
        print("\n❌ Build failed!")
        sys.exit(1)


def build_linux():
    """Build for Linux (.AppImage)"""
    print("=" * 60)
    print("🐧 BUILDING FOR LINUX")
    print("=" * 60)

    options = NUITKA_OPTIONS.copy()

    # Build command
    cmd = ["python", "-m", "nuitka"] + options + ["main.py"]

    print("\nRunning Nuitka...")
    print(" ".join(cmd))

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n✅ Linux build successful!")
        print(f"Output: dist/main")

        # Create AppImage
        create_linux_appimage()
    else:
        print("\n❌ Build failed!")
        sys.exit(1)


def build_macos():
    """Build for macOS (.app)"""
    print("=" * 60)
    print("🍎 BUILDING FOR macOS")
    print("=" * 60)

    options = NUITKA_OPTIONS.copy()
    options.extend([
        "--macos-create-app-bundle",
        f"--macos-app-icon={ICON_FILE}",
        f"--macos-app-name={APP_NAME}",
    ])

    # Build command
    cmd = ["python", "-m", "nuitka"] + options + ["main.py"]

    print("\nRunning Nuitka...")
    print(" ".join(cmd))

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n✅ macOS build successful!")
        print(f"Output: dist/{APP_NAME}.app")

        # Create DMG
        create_macos_dmg()
    else:
        print("\n❌ Build failed!")
        sys.exit(1)


def create_windows_installer():
    """Create Windows installer using NSIS"""
    print("\n📦 Creating Windows installer...")

    nsis_script = f"""
!define APP_NAME "{APP_NAME}"
!define APP_VERSION "{APP_VERSION}"
!define APP_AUTHOR "{APP_AUTHOR}"
!define APP_EXE "main.exe"

Name "${{APP_NAME}}"
OutFile "${{APP_NAME}}-${{APP_VERSION}}-Setup.exe"
InstallDir "$PROGRAMFILES64\\${{APP_NAME}}"

Page directory
Page instfiles

Section "Install"
    SetOutPath $INSTDIR
    File "dist\\${{APP_EXE}}"

    CreateDirectory "$SMPROGRAMS\\${{APP_NAME}}"
    CreateShortcut "$SMPROGRAMS\\${{APP_NAME}}\\${{APP_NAME}}.lnk" "$INSTDIR\\${{APP_EXE}}"
    CreateShortcut "$DESKTOP\\${{APP_NAME}}.lnk" "$INSTDIR\\${{APP_EXE}}"

    WriteUninstaller "$INSTDIR\\Uninstall.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\\${{APP_EXE}}"
    Delete "$INSTDIR\\Uninstall.exe"
    Delete "$SMPROGRAMS\\${{APP_NAME}}\\${{APP_NAME}}.lnk"
    Delete "$DESKTOP\\${{APP_NAME}}.lnk"
    RMDir "$SMPROGRAMS\\${{APP_NAME}}"
    RMDir "$INSTDIR"
SectionEnd
"""

    # Write NSIS script
    with open("installer.nsi", "w") as f:
        f.write(nsis_script)

    # Run NSIS
    try:
        subprocess.run(["makensis", "installer.nsi"], check=True)
        print("✅ Windows installer created!")
    except:
        print("⚠️  NSIS not found. Install NSIS to create installer.")


def create_linux_appimage():
    """Create Linux AppImage"""
    print("\n📦 Creating Linux AppImage...")

    # Create AppDir structure
    app_dir = Path("dist/AppDir")
    app_dir.mkdir(exist_ok=True)

    # Copy executable
    (app_dir / "usr/bin").mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "dist/main", str(app_dir / "usr/bin/primebooks")])

    # Create desktop file
    desktop = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec=primebooks
Icon=primebooks
Categories=Office;Finance;
"""

    (app_dir / "usr/share/applications").mkdir(parents=True, exist_ok=True)
    with open(app_dir / "usr/share/applications/primebooks.desktop", "w") as f:
        f.write(desktop)

    # Create AppRun script
    apprun = f"""#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${{SELF%/*}}
export PATH="${{HERE}}/usr/bin:${{PATH}}"
exec "${{HERE}}/usr/bin/primebooks" "$@"
"""

    with open(app_dir / "AppRun", "w") as f:
        f.write(apprun)

    os.chmod(app_dir / "AppRun", 0o755)

    # Download appimagetool and create AppImage
    try:
        subprocess.run([
            "appimagetool",
            str(app_dir),
            f"{APP_NAME}-{APP_VERSION}-x86_64.AppImage"
        ], check=True)
        print("✅ Linux AppImage created!")
    except:
        print("⚠️  appimagetool not found. Install it to create AppImage.")


def create_macos_dmg():
    """Create macOS DMG installer"""
    print("\n📦 Creating macOS DMG...")

    try:
        subprocess.run([
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", f"dist/{APP_NAME}.app",
            "-ov", "-format", "UDZO",
            f"{APP_NAME}-{APP_VERSION}.dmg"
        ], check=True)
        print("✅ macOS DMG created!")
    except:
        print("⚠️  hdiutil not found.")


def main():
    """Main build function"""
    print("=" * 60)
    print(f"🚀 BUILDING {APP_NAME} v{APP_VERSION}")
    print("=" * 60)

    # Detect platform
    system = platform.system()

    if system == "Windows":
        build_windows()
    elif system == "Darwin":
        build_macos()
    elif system == "Linux":
        build_linux()
    else:
        print(f"❌ Unsupported platform: {system}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ BUILD COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    main()