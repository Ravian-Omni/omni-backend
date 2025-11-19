#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
from pathlib import Path


def build_with_nuitka():
    """Build the application with Nuitka 2.7.12 for Python 3.12"""

    # Clean dist directory
    dist_dir = Path("dist")
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    print("Building with Nuitka 2.7.12 (Python 3.12)...")

    nuitka_cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=standalone",
        "--assume-yes-for-downloads",
        "--show-progress",
        # ============================================================
        # SIZE & SPEED OPTIMIZATIONS (Major impact: -40-50% size)
        # ============================================================
        "--lto=yes",  # Link-Time Optimization: -20% size, +15% speed
        "--remove-output",  # Strip debug info: -15% size
        "--python-flag=-OO",  # Remove docstrings: -8% size
        "--no-pyi-file",  # Skip type stubs: -2% size
        # ============================================================
        # COMPILATION SETTINGS
        # ============================================================
        "--jobs=8",  # Use multiple cores for compilation
        # ============================================================
        # EXCLUDE UNUSED STANDARD LIBRARY (20-50MB savings)
        # ============================================================
        "--nofollow-import-to=tkinter",  # GUI: ~15MB
        "--nofollow-import-to=test",  # Tests: ~10MB
        "--nofollow-import-to=distutils",  # Old packaging: ~5MB
        "--nofollow-import-to=setuptools",  # Packaging: ~8MB
        "--nofollow-import-to=pip",  # Installer: ~12MB
        "--nofollow-import-to=unittest",  # Testing: ~4MB
        # macOS specific exclusions
        "--nofollow-import-to=Foundation",
        "--nofollow-import-to=Cocoa",
        "--nofollow-import-to=AppKit",
        # ============================================================
        # PYTHON FLAGS
        # ============================================================
        "--python-flag=no_site",
        "--python-flag=isolated",
        # ============================================================
        # APPLICATION PACKAGES (from src/)
        # ============================================================
        "--include-package=src",
        "--include-package=src.capabilities",
        "--include-package=src.capabilities.browser_manager",
        "--include-package=src.capabilities.email_manager",
        "--include-package=src.capabilities.file_finder",
        "--include-package=src.capabilities.image_generator",
        "--include-package=src.capabilities.python_developer",
        "--include-package=src.configs",
        "--include-package=src.managers",
        "--include-package=src.routers",
        "--include-package=src.utilities",
        "--include-package=src.omni",
        # ============================================================
        # CORE PACKAGES (from requirements.txt)
        # ============================================================
        "--include-package=autogen",
        "--include-package=fastapi",
        "--include-package=uvicorn",
        "--include-package=starlette",
        "--include-package=pydantic",
        "--include-package=pydantic_core",
        # Playwright and browser
        "--include-package=playwright",
        "--include-package=playwright._impl",
        # Complete browser_use inclusion with all submodules
        "--include-package=browser_use",
        "--include-package=browser_use.agent",
        "--include-package=browser_use.browser",
        "--include-package=browser_use.controller",
        "--include-package=browser_use.dom",
        "--include-package=browser_use.sync",
        "--include-package=browser_use.telemetry",
        # Include browser_use package data
        "--include-package-data=browser_use",
        # LangChain
        "--include-package=langchain",
        "--include-package=langchain_core",
        # "--include-package=langchain_community",
        # HTTP and async
        "--include-package=httpx",
        "--include-package=httpcore",
        "--include-package=websockets",
        "--include-package=anyio",
        "--include-package=sniffio",
        "--include-package=h11",
        # Security and utilities
        "--include-package=cryptography",
        "--include-package=loguru",
        "--include-package=nest_asyncio",
        # Email
        "--include-package=simplegmail",
        # API clients - use actual import names
        "--include-package=tavily",  # Not tavily_python
        "--include-package=together",
        "--include-package=dotenv",  # Not python-dotenv
        # Include package data
        # "--include-package-data=playwright",
        "--include-package-data=certifi",
        "--include-package-data=cryptography",
        "--include-package-data=pydantic",
        # Include data directories
        "--include-data-dir=templates=templates",
        # Uvicorn specific modules
        "--include-module=uvicorn.lifespan.on",
        "--include-module=uvicorn.lifespan.off",
        "--include-module=uvicorn.protocols.http.auto",
        "--include-module=uvicorn.protocols.http.h11_impl",
        "--include-module=uvicorn.protocols.http.httptools_impl",
        "--include-module=uvicorn.protocols.websockets.auto",
        "--include-module=uvicorn.protocols.websockets.websockets_impl",
        "--include-module=uvicorn.protocols.websockets.wsproto_impl",
        "--include-module=uvicorn.loops.auto",
        "--include-module=uvicorn.loops.asyncio",
        "--include-module=uvicorn.loops.uvloop",
        # System modules
        "--include-module=multiprocessing.resource_tracker",
        "--include-module=multiprocessing.spawn",
        "--include-module=encodings",
        "--include-module=certifi",
        "--include-module=src.main",
        # ============================================================
        # OPTIMIZATION PLUGINS
        # ============================================================
        "--follow-imports",
        "--prefer-source-code",
        "--enable-plugin=anti-bloat",
        # ============================================================
        # OUTPUT CONFIGURATION
        # ============================================================
        "--output-dir=dist",
        "--output-filename=ravian",
        # ============================================================
        # METADATA
        # ============================================================
        "--company-name=Ravian AI PVT LTD",
        "--product-name=Ravian AI",
        "--file-version=1.0.0",
        "--product-version=1.0.0",
        "--file-description=Ravian AI - Browser Automation & AI Assistant",
        # ============================================================
        # PLATFORM SPECIFIC
        # ============================================================
        "--windows-console-mode=attach" if sys.platform == "win32" else "",
        (
            "--windows-icon-from-ico=icon.ico"
            if Path("icon.ico").exists() and sys.platform == "win32"
            else ""
        ),
        # Main script (now at root)
        "main.py",
    ]

    # Remove empty strings from command
    nuitka_cmd = [arg for arg in nuitka_cmd if arg]

    # Set environment for build
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())

    # Run Nuitka
    try:
        subprocess.run(nuitka_cmd, check=True, env=env)
        print("Build completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    build_with_nuitka()
