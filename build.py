#!/usr/bin/env python3
"""
Main build script for Python 3.12 FastAPI + AutoGen application
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_python_version():
    """Ensure we're using Python 3.12"""
    version = sys.version_info
    if version.major != 3 or version.minor != 12:
        print(
            f"Warning: This script is designed for Python 3.12, but you're using {version.major}.{version.minor}"
        )
        response = input("Continue anyway? (y/n): ")
        if response.lower() != "y":
            sys.exit(1)


def install_git_requirement():
    """Install the custom browser-use from git"""
    print("Installing custom browser-use from git...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "git+https://github.com/Suryaaa-Rathore/ravian-browser-use.git@ravian_0.3.1",
        ],
        check=True,
    )


def create_requirements_copy():
    """Create a copy of requirements for the build"""
    build_req = Path("build_requirements.txt")

    # Read original requirements
    with open("requirements.txt") as f:
        lines = f.readlines()

    # Process requirements (remove git+ lines for main package install)
    main_reqs = []
    git_reqs = []

    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            if line.startswith("git+"):
                git_reqs.append(line)
            else:
                main_reqs.append(line)

    # Write processed requirements
    with open(build_req, "w") as f:
        f.write("\n".join(main_reqs))

    return build_req, git_reqs


def main():
    print("=== Python 3.12 FastAPI + AutoGen + Browser-Use Packaging ===")

    # Check Python version
    check_python_version()

    # Ensure we're in the right directory
    if not Path("main.py").exists():
        print("Error: main.py not found. Run this script from your project root.")
        sys.exit(1)

    # Step 1: Install build dependencies
    print("\n1. Installing build dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "nuitka", "ordered-set", "zstandard"],
        check=True,
    )

    # Step 2: Process and install requirements
    print("\n2. Installing application requirements...")
    build_req, git_reqs = create_requirements_copy()

    # Install main requirements
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(build_req)], check=True
    )

    # Install git requirements
    for git_req in git_reqs:
        print(f"Installing: {git_req}")
        subprocess.run([sys.executable, "-m", "pip", "install", git_req], check=True)

    # Clean up
    build_req.unlink()

    # Step 3: Setup Playwright browsers
    # print("\n3. Setting up Playwright browsers...")
    # subprocess.run([sys.executable, "build_scripts/setup_browsers.py"], check=True)

    # Step 4: Create Python environment
    print("\n4. Creating Python execution environment...")
    subprocess.run([sys.executable, "build_scripts/create_python_env.py"], check=True)

    # Step 5: Build with Nuitka
    print("\n5. Building application with Nuitka...")
    subprocess.run([sys.executable, "build_scripts/nuitka_build.py"], check=True)

    # Step 6: Copy any additional files needed
    print("\n7. Copying additional files...")
    # Copy .env file if it exists
    if Path(".env").exists():
        shutil.copy(".env", Path("dist") / ".env")
        print("Copied .env file")

    print("\n=== Build Complete! ===")
    print(f"Executable location: dist/app{'.exe' if os.name == 'nt' else ''}")
    # print(f"Launcher script: {launcher}")
    print("\nThe package includes:")
    print("- Your FastAPI application with all dependencies")
    print("- Playwright-managed Chromium browser")
    print("- Python 3.12 environment for code execution")
    print("- Custom browser-use from git")
    # print(f"\nRun your application with: {launcher.name}")


if __name__ == "__main__":
    main()
