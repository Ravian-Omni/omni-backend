"""
Main entry point for the Omni Backend application.
This file provides a convenient way to run the application from the root directory.
"""

import sys
from pathlib import Path

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run the application
from src.main import app, settings

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(settings.PORT), reload=False)
