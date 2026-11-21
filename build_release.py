#!/usr/bin/env python3
"""
build_release.py
=================
Helper script that bundles the GoodSAM ETL executables plus supporting files
into a single release folder (and zip archive).

This script automatically checks for and installs missing dependencies from
requirements.txt before building the executables.

Usage:
    # Build release with automatic dependency installation:
    python build_release.py --version 2024.12.01

    # Skip dependency check if you know everything is installed:
    python build_release.py --version 2024.12.01 --skip-deps

    # Skip rebuilding the EXEs if you've already run PyInstaller:
    python build_release.py --version 2024.12.01 --skip-build

    # Skip both dependencies and build (just package existing files):
    python build_release.py --version 2024.12.01 --skip-deps --skip-build
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST_DIR = ROOT / "dist"
RELEASE_ROOT = ROOT / "release"
GS2RCAPI = ROOT / "GS2RCAPI.py"
REQUIREMENTS_FILE = ROOT / "requirements.txt"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    """Wrapper around subprocess.run with nicer errors."""
    print(f"[CMD] {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=cwd or ROOT)


def check_package_installed(package_name: str) -> bool:
    """Check if a Python package is installed."""
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False


def install_dependencies() -> None:
    """Install missing dependencies from requirements.txt."""
    print("[INFO] Checking dependencies...")

    # Check critical packages first
    critical_packages = {
        'numpy': 'numpy',
        'pandas': 'pandas',
        'requests': 'requests',
        'aiohttp': 'aiohttp',
        'redcap': 'PyCap',
        'truststore': 'truststore',
        'PyInstaller': 'PyInstaller'
    }

    missing = []
    for import_name, pip_name in critical_packages.items():
        if not check_package_installed(import_name):
            missing.append(pip_name)

    if missing:
        print(f"[INFO] Missing dependencies detected: {', '.join(missing)}")
        print(f"[INFO] Installing all dependencies from requirements.txt...")

        if not REQUIREMENTS_FILE.exists():
            print(f"[WARN] {REQUIREMENTS_FILE} not found. Installing critical packages only...")
            for pkg in missing:
                run([sys.executable, "-m", "pip", "install", pkg])
        else:
            # Install from requirements.txt
            run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])

        print("[INFO] Dependencies installed successfully!")
    else:
        print("[INFO] All required dependencies are already installed.")


def build_executable(script_name: str, exe_name: str) -> Path:
    """Invoke PyInstaller to build a single executable."""
    add_data_sep = ";" if os.name == "nt" else ":"
    add_data = f"{GS2RCAPI}{add_data_sep}."
    cmd = [
        "python",
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name",
        exe_name,
        "--add-data",
        add_data,
        script_name,
    ]
    run(cmd)
    exe_path = DIST_DIR / f"{exe_name}.exe" if os.name == "nt" else DIST_DIR / exe_name
    if not exe_path.exists():
        raise FileNotFoundError(f"Expected executable was not created: {exe_path}")
    return exe_path


def copy_with_structure(src: Path, dest: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GoodSAM ETL release bundle.")
    parser.add_argument(
        "--version",
        default=dt.datetime.now().strftime("%Y.%m.%d_%H%M"),
        help="Version string used for the release folder/zip name.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip running PyInstaller (assumes dist/*.exe already exist).",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip dependency checking and installation.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(RELEASE_ROOT),
        help="Directory where the release folder/zip should be created.",
    )
    args = parser.parse_args()

    # Install dependencies if needed (unless --skip-deps is specified)
    if not args.skip_deps:
        install_dependencies()
    else:
        print("[INFO] Skipping dependency check (--skip-deps specified).")

    output_root = Path(args.output_dir)
    release_name = f"GoodSAM_ETL_WideFormat_{args.version}"
    release_dir = output_root / release_name

    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_build:
        print("[INFO] Building executables via PyInstaller…")
        build_executable("GS2RCAPI_GUI_Lite.py", "GS2RC-LITE")
        build_executable("GS2RCAPI_GUI.py", "GS2RC-ADV")
    else:
        print("[INFO] Skipping PyInstaller build (using existing dist/ contents).")

    exe_files = [
        DIST_DIR / ("GS2RC-LITE.exe" if os.name == "nt" else "GS2RC-LITE"),
        DIST_DIR / ("GS2RC-ADV.exe" if os.name == "nt" else "GS2RC-ADV"),
    ]
    for exe in exe_files:
        if not exe.exists():
            raise FileNotFoundError(f"Executable missing: {exe} (build step skipped?)")
        shutil.copy2(exe, release_dir / exe.name)

    include_files = [
        "GS2RCAPI.py",
    ]

    for rel in include_files:
        src = ROOT / rel
        if src.exists():
            shutil.copy2(src, release_dir / src.name)
        else:
            print(f"[WARN] Skipping missing file: {rel}")

    # Zip the release directory
    archive_path = shutil.make_archive(release_dir, "zip", root_dir=release_dir.parent, base_dir=release_dir.name)
    print(f"[DONE] Release folder: {release_dir}")
    print(f"[DONE] Release archive: {archive_path}")


if __name__ == "__main__":
    main()
