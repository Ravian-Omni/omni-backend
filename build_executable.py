#!/usr/bin/env python3
import subprocess
import sys
import os
from pathlib import Path


def create_base_venv():
    """Create base virtual environment for bundling"""
    print("📦 Creating base virtual environment...")

    try:
        # Run the base venv creation script
        result = subprocess.run([
            sys.executable, "create_base_venv.py", "--for-build"
        ], check=True, capture_output=True, text=True)

        print("✅ Base virtual environment created successfully!")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to create base virtual environment: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False


def build_executable():
    """Build the FastAPI executable using PyInstaller"""
    print("🚀 Building FastAPI executable...")

    # First create the base virtual environment
    if not create_base_venv():
        return False

    try:
        # Run PyInstaller with the spec file
        result = subprocess.run([
            sys.executable, "-m", "PyInstaller",
            "--clean",  # Clean cache and remove temporary files
            "main.spec"
        ], check=True, capture_output=True, text=True)

        print("✅ Build completed successfully!")
        print(
            f"Executable created at: {os.path.abspath('dist/omni-backend-app')}")

    except subprocess.CalledProcessError as e:
        print(f"❌ Build failed with error: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False

    return True


if __name__ == "__main__":
    success = build_executable()
    sys.exit(0 if success else 1)
