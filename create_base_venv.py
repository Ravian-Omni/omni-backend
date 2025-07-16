#!/usr/bin/env python3
"""
Script to create a base virtual environment with common packages for bundling with the executable.
This virtual environment will be copied for each new project to provide isolation.
"""

import subprocess
import sys
import shutil
from pathlib import Path
import argparse
from loguru import logger

# Common packages that should be pre-installed in the base environment
BASE_PACKAGES = [
    "requests",
    "beautifulsoup4",
    "lxml",
    "pandas",
    "numpy",
    "matplotlib",
    "seaborn",
    "pillow",
    "openpyxl",
    "python-dateutil",
    "urllib3",
    "certifi",
    "charset-normalizer",
    "idna",
    "six",
    "pytz",
    "setuptools",
    "wheel",
]


def create_base_venv(venv_path: Path, python_executable: str = None) -> bool:
    """
    Create a base virtual environment with common packages.

    Args:
        venv_path: Path where the virtual environment should be created
        python_executable: Path to Python executable to use (defaults to current)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Remove existing venv if it exists
        if venv_path.exists():
            logger.info(
                f"Removing existing virtual environment at {venv_path}")
            shutil.rmtree(venv_path)

        # Use provided Python executable or current one
        python_exe = python_executable or sys.executable

        logger.info(f"Creating base virtual environment at {venv_path}")
        logger.info(f"Using Python executable: {python_exe}")

        # Create the virtual environment
        subprocess.run([
            python_exe, "-m", "venv", str(venv_path)
        ], check=True, capture_output=True, text=True)

        # Get pip path
        if sys.platform == "win32":
            pip_path = venv_path / "Scripts" / "pip.exe"
        else:
            pip_path = venv_path / "bin" / "pip"

        # Upgrade pip
        logger.info("Upgrading pip...")
        subprocess.run([
            str(pip_path), "install", "--upgrade", "pip"
        ], check=True, capture_output=True, text=True)

        # Install base packages
        logger.info(f"Installing base packages: {', '.join(BASE_PACKAGES)}")
        subprocess.run([
            str(pip_path), "install"
        ] + BASE_PACKAGES, check=True, capture_output=True, text=True)

        logger.info("Base virtual environment created successfully!")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create base virtual environment: {e}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Create a base virtual environment for bundling")
    parser.add_argument(
        "--venv-path",
        type=Path,
        default=Path("base_venv"),
        help="Path where the base virtual environment should be created (default: base_venv)"
    )
    parser.add_argument(
        "--python",
        type=str,
        help="Path to Python executable to use (defaults to current Python)"
    )
    parser.add_argument(
        "--for-build",
        action="store_true",
        help="Create in build directory for bundling with executable"
    )

    args = parser.parse_args()

    # If --for-build is specified, create in build directory
    if args.for_build:
        build_dir = Path("build")
        build_dir.mkdir(exist_ok=True)
        venv_path = build_dir / "base_venv"
    else:
        venv_path = args.venv_path

    success = create_base_venv(venv_path, args.python)

    if success:
        logger.info(f"Base virtual environment ready at: {venv_path}")
        if args.for_build:
            logger.info(
                "This environment is ready to be bundled with the executable")
    else:
        logger.error("Failed to create base virtual environment")
        sys.exit(1)


if __name__ == "__main__":
    main()
