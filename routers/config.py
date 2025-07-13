# In your main FastAPI file (main.py)
from fastapi import HTTPException, APIRouter
from configs.settings import settings
from typing import Dict
import time

router = APIRouter()

# Get all settings
@router.get("/api/settings")
async def get_all_settings():
    """Get all current settings"""
    return {
        "settings": settings.get_all_settings(),
        "timestamp": time.time()
    }

# Get specific setting
@router.get("/api/settings/{key}")
async def get_setting(key: str):
    """Get specific setting value"""
    if not hasattr(settings, key):
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    
    value = settings.get_setting(key)
    return {
        "key": key,
        "value": value,
        "timestamp": time.time()
    }

# Update single setting
@router.put("/api/settings/{key}")
async def update_setting(key: str, value: str):
    """Update a single setting"""
    success = settings.update_setting(key, value)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    
    return {
        "message": f"Setting '{key}' updated successfully",
        "key": key,
        "value": value,
        "timestamp": time.time()
    }

# Update multiple settings
@router.post("/api/settings/bulk")
async def update_multiple_settings(updates: Dict[str, str]):
    """Update multiple settings at once"""
    results = settings.update_settings(updates)
    
    successful = {k: v for k, v in results.items() if v}
    failed = [k for k, v in results.items() if not v]
    
    return {
        "message": f"Updated {len(successful)} settings",
        "successful": list(successful.keys()),
        "failed": failed,
        "timestamp": time.time()
    }
