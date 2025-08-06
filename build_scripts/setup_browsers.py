#!/usr/bin/env python3
import subprocess
import sys
import os
from pathlib import Path

def setup_playwright_browsers():
    """Download browsers using Playwright's built-in mechanism"""
    
    # Create directory for browsers
    browsers_dir = Path("build_resources/playwright-browsers")
    browsers_dir.mkdir(parents=True, exist_ok=True)
    
    print("Installing Playwright browsers...")
    
    # Set custom path for browsers
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browsers_dir.absolute())
    
    # Install chromium only (to reduce package size)
    subprocess.run([
        sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"
    ], check=True)
    
    print(f"Chromium installed to: {browsers_dir}")
    print("Browser setup complete!")

if __name__ == "__main__":
    setup_playwright_browsers()