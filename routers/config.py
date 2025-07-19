# In your main FastAPI file (main.py)
from fastapi import HTTPException, APIRouter
from configs.settings import settings
from typing import Dict
import time
import json
from datetime import datetime
import base64

router = APIRouter()

# Get all settings
@router.get("/api/settings")
async def get_all_settings():
    """Get all current settings"""
    return {
        "settings": settings.get_all_settings(),
        "timestamp": time.time()
    }

# # Get specific setting
# @router.get("/api/settings/{key}")
# async def get_setting(key: str):
#     """Get specific setting value"""
#     if not hasattr(settings, key):
#         raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    
#     value = settings.get_setting(key)
#     return {
#         "key": key,
#         "value": value,
#         "timestamp": time.time()
#     }

# # Update single setting
# @router.put("/api/settings/{key}")
# async def update_setting(key: str, value: str):
#     """Update a single setting"""
#     success = settings.update_setting(key, value)
    
#     if not success:
#         raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    
#     return {
#         "message": f"Setting '{key}' updated successfully",
#         "key": key,
#         "value": value,
#         "timestamp": time.time()
#     }

# # Update multiple settings
# @router.post("/api/settings/bulk")
# async def update_multiple_settings(updates: Dict[str, str]):
#     """Update multiple settings at once"""
#     results = settings.update_settings(updates)
    
#     successful = {k: v for k, v in results.items() if v}
#     failed = [k for k, v in results.items() if not v]
    
#     return {
#         "message": f"Updated {len(successful)} settings",
#         "successful": list(successful.keys()),
#         "failed": failed,
#         "timestamp": time.time()
#     }




@router.put("/api/settings/user-token")
async def update_user_token(token: str):
    """Update USER_TOKEN setting with basic JWT validation"""
    
    # Basic JWT format validation
    try:
        # Check if token has 3 parts separated by dots
        parts = token.split('.')
        if len(parts) != 3:
            raise HTTPException(status_code=400, detail="Invalid JWT token format - must have 3 parts separated by dots")
        
        # Try to decode the payload (middle part) to validate it's a valid JWT
        header_part, payload_part, signature_part = parts
        
        # Add padding if needed for base64 decoding
        payload_part += '=' * (4 - len(payload_part) % 4)
        
        # Decode payload to check if it's valid JSON
        decoded_payload = base64.urlsafe_b64decode(payload_part.encode())
        payload = json.loads(decoded_payload)
        
        # Optional: Check if token is expired
        if 'exp' in payload:
            exp_timestamp = payload['exp']
            if datetime.utcnow().timestamp() > exp_timestamp:
                raise HTTPException(status_code=400, detail="JWT token is expired")
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JWT token - payload is not valid JSON")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JWT token format")
    
    # Update the setting
    success = settings.update_setting("USER_TOKEN", token)
    
    if not success:
        # If USER_TOKEN doesn't exist, add it dynamically
        settings.USER_TOKEN = token
        success = True
    
    return {
        "message": "USER_TOKEN updated successfully",
        "token_preview": f"{token[:20]}...{token[-10:]}" if len(token) > 30 else "***",
        "expires_at": datetime.fromtimestamp(payload.get('exp')).isoformat() if payload.get('exp') else None,
        "timestamp": time.time()
    }

@router.get("/api/settings/user-token")
async def get_user_token():
    """Get current USER_TOKEN (masked for security)"""
    token = getattr(settings, 'USER_TOKEN', None)
    
    if not token:
        raise HTTPException(status_code=404, detail="USER_TOKEN not set")
    
    # Show only preview for security
    token_preview = f"{token[:20]}...{token[-10:]}" if len(token) > 30 else "***"
    
    return {
        "key": "USER_TOKEN",
        "token_preview": token_preview,
        "is_set": True,
        "timestamp": time.time()
    }

@router.delete("/api/settings/user-token")
async def clear_user_token():
    """Clear/remove USER_TOKEN"""
    if hasattr(settings, 'USER_TOKEN'):
        settings.USER_TOKEN = None
        return {
            "message": "USER_TOKEN cleared successfully",
            "timestamp": time.time()
        }
    else:
        raise HTTPException(status_code=404, detail="USER_TOKEN not found")