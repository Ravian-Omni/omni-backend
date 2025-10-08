#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


def setup_playwright_browsers():
    """Download browsers using Playwright's built-in mechanism"""

    # Create directory for browsers
    browsers_dir = Path("build_resources/playwright-browsers")
    browsers_dir.mkdir(parents=True, exist_ok=True)

    print("Installing Playwright browsers...")

    # Install playwright
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)

    # Download Chromium using playwright
    # Set custom path for browsers
    import os

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir.absolute())

    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"], check=True
    )

    print(f"Chromium installed to: {browsers_dir}")
    print("Browser setup complete!")


if __name__ == "__main__":
    setup_playwright_browsers()
