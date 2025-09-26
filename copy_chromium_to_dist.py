#!/usr/bin/env python3
"""
Script to copy the entire Chromium application to the dist folder
alongside the executable for distribution.
"""

import shutil
import os
from pathlib import Path
from loguru import logger


def copy_chromium_to_dist():
    """Copy the entire Chromium application to the dist folder"""
    try:
        # Source Chromium path
        source_chromium = Path(
            "/Users/voidfinder/Library/Caches/ms-playwright/chromium-1169/chrome-mac/Chromium.app")

        # Destination path in dist folder
        dist_dir = Path("dist")
        dest_chromium = dist_dir / "Chromium.app"

        # Check if source exists
        if not source_chromium.exists():
            logger.error(f"Source Chromium not found: {source_chromium}")
            return False

        # Create dist directory if it doesn't exist
        dist_dir.mkdir(exist_ok=True)

        # Remove existing Chromium if it exists
        if dest_chromium.exists():
            logger.info("Removing existing Chromium from dist...")
            shutil.rmtree(dest_chromium)

        # Copy the entire Chromium.app
        logger.info(
            f"Copying Chromium from {source_chromium} to {dest_chromium}")
        shutil.copytree(source_chromium, dest_chromium)

        # Make the executable properly executable
        chromium_executable = dest_chromium / "Contents" / "MacOS" / "Chromium"
        if chromium_executable.exists():
            chromium_executable.chmod(0o755)
            logger.info(f"Made Chromium executable: {chromium_executable}")

        # Check the size
        def get_dir_size(path):
            total = 0
            for entry in os.scandir(path):
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += get_dir_size(entry.path)
            return total

        size_mb = get_dir_size(dest_chromium) / (1024 * 1024)
        logger.info(f"Chromium copied successfully! Size: {size_mb:.1f} MB")

        return True

    except Exception as e:
        logger.error(f"Failed to copy Chromium: {e}")
        return False


def verify_chromium_copy():
    """Verify that the Chromium copy is complete and functional"""
    dist_chromium = Path("dist/Chromium.app")

    if not dist_chromium.exists():
        logger.error("Chromium.app not found in dist folder")
        return False

    # Check essential components
    essential_files = [
        "Contents/MacOS/Chromium",
        "Contents/Info.plist",
        "Contents/Frameworks/Chromium Framework.framework/Chromium Framework"
    ]

    missing_files = []
    for file_path in essential_files:
        full_path = dist_chromium / file_path
        if not full_path.exists():
            missing_files.append(file_path)

    if missing_files:
        logger.error(f"Missing essential files: {missing_files}")
        return False

    logger.info("✅ Chromium copy verification passed!")
    return True


def main():
    logger.info("🌐 Copying Chromium to dist folder...")

    if copy_chromium_to_dist():
        if verify_chromium_copy():
            logger.info("🎉 Chromium successfully copied and verified!")
            logger.info(
                "💡 Update your settings to use: dist/Chromium.app/Contents/MacOS/Chromium")
        else:
            logger.error("❌ Chromium copy verification failed")
    else:
        logger.error("❌ Failed to copy Chromium")


if __name__ == "__main__":
    main()
