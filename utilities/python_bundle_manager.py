#!/usr/bin/env python3
"""
Python Bundle Manager for Electron App.
Handles finding and using bundled Python distribution.
"""

import sys
from pathlib import Path
from typing import Optional


class PythonBundleManager:
    """Manages bundled Python distribution for Electron app."""

    @staticmethod
    def get_bundled_python_path() -> Optional[Path]:
        """
        Get the path to the bundled Python executable.

        Returns:
            Path to bundled Python executable, or None if not found.
        """
        if getattr(sys, 'frozen', False):
            # Running as executable - look for bundled Python
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller bundle
                bundle_dir = Path(sys._MEIPASS)
            else:
                # Other bundling methods
                bundle_dir = Path(sys.executable).parent

            # Look for bundled Python in various possible locations
            possible_paths = [
                bundle_dir / "bundled_python" / "python-darwin-arm64" / "python" / "bin" / "python3",
                bundle_dir / "bundled_python" / "python" / "bin" / "python3",
                bundle_dir / "python" / "bin" / "python3",
                bundle_dir / "Python.framework" / "Versions" / "3.12" / "bin" / "python3",
            ]

            for python_path in possible_paths:
                if python_path.exists() and python_path.is_file():
                    return python_path

        else:
            # Development mode - look for bundled Python in project directory
            project_root = Path(__file__).parent.parent
            bundled_python = project_root / "bundled_python" / \
                "python-darwin-arm64" / "python" / "bin" / "python3"

            if bundled_python.exists():
                return bundled_python

        return None

    @staticmethod
    def get_system_python_fallback() -> str:
        """Get system Python as fallback if bundled Python not found."""
        # Try common system Python locations for ARM64 Mac
        possible_pythons = [
            "python3",                          # Most common
            "/opt/homebrew/bin/python3",        # Homebrew ARM64
            "/usr/local/bin/python3",           # Homebrew Intel (Rosetta)
            "/usr/bin/python3",                 # System Python
            "python",                           # Fallback
        ]

        import subprocess

        for python_cmd in possible_pythons:
            try:
                # Test if this Python works and is ARM64 compatible
                result = subprocess.run([
                    python_cmd, "-c",
                    "import platform; print(f'{platform.python_version()}:{platform.machine()}')"
                ], check=True, capture_output=True, text=True)

                version_arch = result.stdout.strip()
                if "arm64" in version_arch or "aarch64" in version_arch:
                    return python_cmd

            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

        # Final fallback - just use python3
        return "python3"

    @staticmethod
    def get_best_python_executable() -> str:
        """
        Get the best available Python executable.

        Returns:
            Path to Python executable (bundled if available, system fallback).
        """
        # Try bundled Python first
        bundled_python = PythonBundleManager.get_bundled_python_path()
        if bundled_python:
            return str(bundled_python)

        # Fall back to system Python
        return PythonBundleManager.get_system_python_fallback()


if __name__ == "__main__":
    # Test the bundle manager
    print("🔍 Testing Python Bundle Manager...")

    bundled = PythonBundleManager.get_bundled_python_path()
    if bundled:
        print(f"✅ Found bundled Python: {bundled}")
    else:
        print("❌ No bundled Python found")

    system = PythonBundleManager.get_system_python_fallback()
    print(f"🔄 System Python fallback: {system}")

    best = PythonBundleManager.get_best_python_executable()
    print(f"🏆 Best Python executable: {best}")

    # Test the chosen Python
    import subprocess
    try:
        result = subprocess.run([
            best, "--version"
        ], check=True, capture_output=True, text=True)
        print(f"🐍 Python version: {result.stdout.strip()}")
    except Exception as e:
        print(f"❌ Error testing Python: {e}")
