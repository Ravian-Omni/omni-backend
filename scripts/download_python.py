#!/usr/bin/env python3
"""
Script to download Python embeddable distributions for bundling with Electron app.
"""

import os
import platform
import urllib.request
import zipfile
import tarfile
from pathlib import Path


def get_python_download_info():
    """Get Python download URLs for macOS ARM64 only."""
    python_version = "3.12.7"  # Use stable version

    downloads = {
        "darwin-arm64": {
            # Portable Python build for macOS Apple Silicon
            "url": f"https://github.com/indygreg/python-build-standalone/releases/download/20241016/cpython-{python_version}+20241016-aarch64-apple-darwin-install_only.tar.gz",
            "filename": f"python-{python_version}-darwin-arm64.tar.gz",
            "extract_to": "python-darwin-arm64"
        }
    }

    return downloads


def download_python_for_platform(target_platform, output_dir):
    """Download Python for a specific platform."""
    downloads = get_python_download_info()

    if target_platform not in downloads:
        print(f"Unsupported platform: {target_platform}")
        return False

    info = downloads[target_platform]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    download_path = output_path / info["filename"]
    extract_path = output_path / info["extract_to"]

    print(f"Downloading Python for {target_platform}...")
    print(f"URL: {info['url']}")

    try:
        urllib.request.urlretrieve(info["url"], download_path)
        print(f"Downloaded to: {download_path}")

        # Extract the archive
        print(f"Extracting to: {extract_path}")
        extract_path.mkdir(parents=True, exist_ok=True)

        if download_path.suffix == '.zip':
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
        elif download_path.suffix in ['.tgz', '.gz']:
            with tarfile.open(download_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_path)

        print(f"✅ Python for {target_platform} ready at: {extract_path}")
        return True

    except Exception as e:
        print(f"❌ Failed to download Python for {target_platform}: {e}")
        return False


def download_for_arm64_mac():
    """Download Python for Apple Silicon Mac only."""
    output_dir = Path(__file__).parent.parent / "bundled_python"

    # Check if we're on ARM64 Mac
    current_arch = platform.machine().lower()
    if current_arch not in ['arm64', 'aarch64']:
        print("❌ This script is designed for Apple Silicon Macs only")
        print(f"Detected architecture: {current_arch}")
        return None

    print("🍎 Detected Apple Silicon Mac - downloading ARM64 Python...")

    platform_name = "darwin-arm64"
    print(f"\n{'='*50}")
    print(f"Downloading Python for {platform_name}...")
    success = download_python_for_platform(platform_name, output_dir)

    if success:
        print(f"\n🎉 Python successfully downloaded and ready for bundling!")
        extract_path = output_dir / \
            get_python_download_info()[platform_name]["extract_to"]
        print(f"📁 Location: {extract_path}")
        return extract_path
    else:
        print(f"\n❌ Failed to download Python for {platform_name}")
        return None


if __name__ == "__main__":
    # Download Python for ARM64 Mac only
    python_path = download_for_arm64_mac()

    if python_path:
        print(f"\n✅ Next steps:")
        print(f"1. Use this Python path in your build: {python_path}")
        print(f"2. Bundle this directory with your Electron app")
        print(f"3. Update VenvManager to use bundled Python")
