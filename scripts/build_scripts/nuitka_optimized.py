#!/usr/bin/env python3
"""
Simple Nuitka Build Script for Ravian AI
Just run: python build.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ============================================================
# CONFIGURATION - Change these as needed
# ============================================================
APP_NAME = "ravian"
VERSION = "1.0.0"
COMPANY = "Ravian AI PVT LTD"
DESCRIPTION = "Ravian AI - Browser Automation & AI Assistant"

# ============================================================
# CLEANUP OLD BUILD
# ============================================================
print("Cleaning old builds...")
if Path("dist").exists():
    shutil.rmtree("dist")

# ============================================================
# BUILD COMMAND
# ============================================================
print(f"Building {APP_NAME} v{VERSION}...")

build_command = [
    sys.executable, "-m", "nuitka",
    "--mode=standalone",
    "--assume-yes-for-downloads",
    "--show-progress",
    
    # ========================================
    # OPTIMIZATIONS (Makes it smaller & faster)
    # ========================================
    "--lto=yes",                    # 20% smaller, 15% faster
    "--remove-output",              # Remove debug info (15% smaller)
    "--python-flag=-OO",            # Remove docstrings (8% smaller)
    "--no-pyi-file",                # Skip type files (2% smaller)
    f"--jobs={os.cpu_count() or 4 if os.getenv('CI') else max(1, (os.cpu_count() or 4) - 2)}",  # Leave 2 cores free for other tasks
    
    # ========================================
    # PYTHON FLAGS
    # ========================================
    "--python-flag=no_site",
    "--python-flag=isolated",
    
    # ========================================
    # EXCLUDE UNUSED STUFF (Saves 50-80MB)
    # ========================================
    "--nofollow-import-to=tkinter",
    "--nofollow-import-to=test",
    "--nofollow-import-to=distutils",
    "--nofollow-import-to=setuptools",
    "--nofollow-import-to=pip",
    "--nofollow-import-to=unittest",
    
    # ========================================
    # INCLUDE YOUR PACKAGES
    # ========================================
    # Application packages (from src/)
    "--include-package=src",
    "--include-package=src.capabilities",
    "--include-package=src.configs",
    "--include-package=src.managers",
    "--include-package=src.routers",
    "--include-package=src.utilities",
    "--include-package=src.omni",

    # Third-party packages
    "--include-package=autogen",
    "--include-package=fastapi",
    "--include-package=uvicorn",
    "--include-package=starlette",
    "--include-package=pydantic",
    "--include-package=pydantic_core",
    "--include-package=playwright",
    "--include-package=browser_use",      # This includes ALL browser_use submodules
    "--include-package=langchain",
    "--include-package=langchain_core",
    "--include-package=httpx",
    "--include-package=httpcore",
    "--include-package=websockets",
    "--include-package=anyio",
    "--include-package=sniffio",
    "--include-package=h11",
    "--include-package=cryptography",
    "--include-package=loguru",
    "--include-package=nest_asyncio",
    "--include-package=simplegmail",
    "--include-package=tavily",
    "--include-package=together",
    "--include-package=dotenv",
    
    # ========================================
    # INCLUDE DATA FILES
    # ========================================
    "--include-package-data=browser_use",
    "--include-package-data=certifi",
    "--include-package-data=cryptography",
    "--include-package-data=pydantic",

    # ========================================
    # INCLUDE DATA DIRECTORIES
    # ========================================
    "--include-data-dir=templates=templates",

    # ========================================
    # CRITICAL MODULES (Nuitka sometimes misses these)
    # ========================================
    "--include-module=multiprocessing.resource_tracker",
    "--include-module=multiprocessing.spawn",
    "--include-module=encodings",
    "--include-module=src.main",
    
    # ========================================
    # PLUGINS
    # ========================================
    "--prefer-source-code",
    "--enable-plugin=anti-bloat",
    
    # ========================================
    # OUTPUT
    # ========================================
    "--output-dir=dist",
    f"--output-filename={APP_NAME}",
    
    # ========================================
    # METADATA
    # ========================================
    f"--company-name={COMPANY}",
    f"--product-name={APP_NAME}",
    f"--file-version={VERSION}",
    f"--product-version={VERSION}",
    f"--file-description={DESCRIPTION}",
    
    # ========================================
    # MAIN FILE
    # ========================================
    "main.py",
]

# ========================================
# WINDOWS SPECIFIC
# ========================================
if sys.platform == "win32":
    build_command.insert(-1, "--windows-console-mode=attach")
    if Path("icon.ico").exists():
        build_command.insert(-1, "--windows-icon-from-ico=icon.ico")

# ========================================
# macOS SPECIFIC
# ========================================
if sys.platform == "darwin":
    build_command.extend([
        "--nofollow-import-to=Foundation",
        "--nofollow-import-to=Cocoa",
        "--nofollow-import-to=AppKit",
    ])

# ============================================================
# RUN BUILD
# ============================================================
env = os.environ.copy()
env["PYTHONPATH"] = str(Path.cwd())

try:
    subprocess.run(build_command, check=True, env=env)
    print(f"\n✓ SUCCESS! Built: dist/{APP_NAME}")
except subprocess.CalledProcessError:
    print("\n✗ BUILD FAILED!")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n✗ Cancelled by user")
    sys.exit(1)