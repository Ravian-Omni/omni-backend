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
# CLEANUP OLD BUILD (Optional - comment out for incremental)
# ============================================================
CLEAN_BUILD = os.getenv("CLEAN_BUILD", "false").lower() == "true"

if CLEAN_BUILD:
    print("🧹 Cleaning old builds (CLEAN_BUILD=true)...")
    if Path("dist").exists():
        shutil.rmtree("dist")
    if Path(".nuitka").exists():
        shutil.rmtree(".nuitka")
else:
    print("⚡ Using incremental build (Nuitka caches unchanged files automatically)")

# ============================================================
# BUILD COMMAND
# ============================================================
print(f"🔨 Building {APP_NAME} v{VERSION} for macOS...")

build_command = [
    sys.executable,
    "-m",
    "nuitka",
    "--standalone",
    "--assume-yes-for-downloads",
    "--show-progress",
    "--show-scons",  # Shows Scons compilation progress
    # ========================================
    # OPTIMIZATIONS (Makes it smaller & faster)
    # ========================================
    "--lto=no",  # Changed from yes - faster builds, avoids some closure issues
    # "--remove-output",  # Remove debug info (15% smaller)
    "--python-flag=-O",  # Changed from -OO - keeps docstrings for dynamic code
    "--no-pyi-file",  # Skip type files (2% smaller)
    f"--jobs={max(1, (os.cpu_count() or 4) - 2)}",  # Leave 2 cores free for macOS responsiveness
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
    # macOS specific exclusions
    "--nofollow-import-to=Foundation",
    "--nofollow-import-to=Cocoa",
    "--nofollow-import-to=AppKit",
    "--nofollow-import-to=PyObjC",
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
    "--include-package=autogen_core",
    "--include-package=composio",
    "--include-package=composio_autogen",  # Include it
    "--include-package=fastapi",
    "--include-package=uvicorn",
    "--include-package=starlette",
    "--include-package=pydantic",
    "--include-package=pydantic_core",
    "--include-package=playwright",
    "--include-package=browser_use",
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
    # OpenTelemetry packages
    "--include-package=opentelemetry",
    "--include-package=opentelemetry.context",
    "--include-package=opentelemetry.trace",
    "--include-package=opentelemetry.util",
    # Explicitly include the missing module
    "--include-module=opentelemetry.context.contextvars_context",
    # ========================================
    # INCLUDE DATA FILES
    # ========================================
    "--include-package-data=browser_use",
    "--include-package-data=certifi",
    "--include-package-data=cryptography",
    "--include-package-data=pydantic",
    "--include-package-data=opentelemetry",
    "--include-package-data=composio",
    "--include-package-data=composio_autogen",
    # ========================================
    # INCLUDE DATA DIRECTORIES
    # ========================================
    "--include-data-dir=templates=templates",
    # ========================================
    # CRITICAL MODULES
    # ========================================
    "--include-module=multiprocessing.resource_tracker",
    "--include-module=multiprocessing.spawn",
    "--include-module=encodings",
    "--include-module=src.main",
    # ========================================
    # PLUGINS
    # ========================================
    "--prefer-source-code",  # Helps with dynamic code like composio
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

# ============================================================
# RUN BUILD
# ============================================================
env = os.environ.copy()
env["PYTHONPATH"] = str(Path.cwd())

# Enable ccache for macOS (works with Clang)
if shutil.which("ccache"):
    env["CC"] = "ccache clang"
    env["CXX"] = "ccache clang++"
    print("✅ ccache detected - C compilation will be cached")
    # Show ccache stats before build
    try:
        result = subprocess.run(["ccache", "-s"], capture_output=True, text=True)
        if result.returncode == 0:
            print("📊 Current ccache stats:")
            for line in result.stdout.split("\n")[:3]:
                if line.strip():
                    print(f"   {line}")
    except Exception as e:
        print(f"⚠️  Could not get ccache stats: {e}")
else:
    print("💡 Tip: Install ccache for 5-10x faster rebuilds:")
    print("   brew install ccache")

try:
    subprocess.run(build_command, check=True, env=env)
    print(f"\n✅ SUCCESS! Built: dist/{APP_NAME}")

    dist_path = Path(f"dist/{APP_NAME}.dist")
    if dist_path.exists():
        size_mb = sum(f.stat().st_size for f in dist_path.rglob("*") if f.is_file()) / (
            1024 * 1024
        )
        print(f"📦 Binary size: {size_mb:.1f} MB")

    if shutil.which("ccache"):
        print("\n📊 ccache stats after build:")
        subprocess.run(["ccache", "-s"], capture_output=False)

    print("\n💡 Tips:")
    print("   • Nuitka automatically caches in .nuitka/ folder")
    print("   • Only changed files are recompiled")
    print("   • Use 'CLEAN_BUILD=true python build.py' for fresh build")

except subprocess.CalledProcessError:
    print("\n❌ BUILD FAILED!")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n⚠️  Cancelled by user")
    sys.exit(1)
