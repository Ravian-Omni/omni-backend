# llm_config_manager.py - Pure date-based encryption (no settings dependency)
from typing import Dict, Any, Tuple
import asyncio
import time
import json
import base64
import os
import hashlib
from datetime import date
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend
from utilities.api_client import api_client
import copy
class PureDateEncryption:
    """Pure date-based AES-256-GCM encryption - no global settings"""
    
    KEY_SIZE = 32  # 256 bits
    IV_SIZE = 12   # 96 bits for GCM
    TAG_SIZE = 16  # 128 bits authentication tag
    SALT_SIZE = 32 # 256 bits salt for key derivation
    
    @staticmethod
    def _get_date_based_key() -> bytes:
        """Get encryption key based purely on current date"""
        # Use current date as primary key (YYYY-MM-DD format)
        current_date = date.today().isoformat()
        
        # Create deterministic key from date only
        # Using same fixed salt as server ensures compatibility
        fixed_salt = "llm_config_date_encryption_2025"
        
        # Combine date + fixed salt for master key
        combined = f"{current_date}:{fixed_salt}".encode()
        return hashlib.sha256(combined).digest()
    
    @staticmethod
    def decrypt_data(encrypted_data: str) -> Dict[str, Any]:
        """Decrypt data using current date as key"""
        try:
            current_date = date.today().isoformat()
            print(f"🔓 Client decrypting with date key: {current_date}")
            
            # Decode base64
            encrypted_blob = base64.b64decode(encrypted_data.encode())
            
            # Extract components
            salt = encrypted_blob[:PureDateEncryption.SALT_SIZE]
            iv = encrypted_blob[PureDateEncryption.SALT_SIZE:PureDateEncryption.SALT_SIZE + PureDateEncryption.IV_SIZE]
            tag = encrypted_blob[PureDateEncryption.SALT_SIZE + PureDateEncryption.IV_SIZE:PureDateEncryption.SALT_SIZE + PureDateEncryption.IV_SIZE + PureDateEncryption.TAG_SIZE]
            ciphertext = encrypted_blob[PureDateEncryption.SALT_SIZE + PureDateEncryption.IV_SIZE + PureDateEncryption.TAG_SIZE:]
            
            # Get date-based master key
            master_key = PureDateEncryption._get_date_based_key()
            
            # Derive decryption key using HKDF
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=PureDateEncryption.KEY_SIZE,
                salt=salt,
                info=b'llm_config_encryption',
                backend=default_backend()
            )
            decryption_key = hkdf.derive(master_key)
            
            # Decrypt with AES-256-GCM
            cipher = Cipher(algorithms.AES(decryption_key), modes.GCM(iv, tag), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Convert back to dict
            return json.loads(decrypted_data.decode())
            
        except Exception as e:
            current_date = date.today().isoformat()
            raise Exception(f"Decryption failed with date key {current_date}: {str(e)}")
    
    @staticmethod
    def get_current_date_info() -> Dict[str, Any]:
        """Get information about current date-based encryption"""
        current_date = date.today().isoformat()
        
        return {
            "algorithm": "AES-256-GCM",
            "primary_key": f"Date-based ({current_date})",
            "key_rotation": "Daily (automatic)",
            "key_size_bits": PureDateEncryption.KEY_SIZE * 8,
            "iv_size_bits": PureDateEncryption.IV_SIZE * 8,
            "tag_size_bits": PureDateEncryption.TAG_SIZE * 8,
            "salt_size_bits": PureDateEncryption.SALT_SIZE * 8,
            "key_derivation": "HKDF-SHA256",
            "authentication": "GCM (Galois/Counter Mode)",
            "security_level": "HIGH",
            "key_source": "Current system date",
            "no_storage": "Keys generated on-demand",
            "key_expiry": "End of day (00:00 UTC)"
        }

class LLMConfigManager:
    """LLM Configuration Manager with pure date-based encryption"""
    
    _cache: Dict[str, Any] = {}
    _cache_time: float = 0
    _cache_date: str = ""  # Track which date the cache was created
    
    @classmethod
    def get_config(cls, config_name: str) -> Dict[str, Any]:
        """Get LLM configuration by name - Main method to use"""
        configs = cls._get_all_configs()
        
        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(f"Config '{config_name}' not found. Available: {available}")
        
        # config_data = configs[config_name]
        config_data = copy.deepcopy(configs[config_name])
        return {"config_list": [config_data]}
    
    @classmethod
    def get_available_configs(cls) -> list:
        """Get list of available configuration names"""
        configs = cls._get_all_configs()
        return list(configs.keys())
    
    @classmethod
    def _get_all_configs(cls) -> Dict[str, Any]:
        """Get all configs - decrypt if needed, check date-based cache validity"""
        current_date = date.today().isoformat()
        
        # Check if cache is valid for current date
        if cls._cache and cls._cache_date == current_date:
            print(f"📋 Using cached configs for date: {current_date}")
            return cls._cache
        
        # Cache is invalid or from different date - fetch fresh data
        try:
            print(f"🔄 Fetching fresh configs for date: {current_date}")
            
            response = asyncio.run(api_client.get("/chats/api_keys"))
            response = response.standard_response()
            
            if response["success"]:
                # Extract encrypted data from StandardResponse format
                raw_data = response["data"]["configs"]  # Changed from response["data"] to response["data"]["configs"]
                
                if isinstance(raw_data, str):
                    # Data is encrypted, decrypt with current date key
                    print(f"🔓 Decrypting with date key: {current_date}")
                    decrypted_data = PureDateEncryption.decrypt_data(raw_data)
                    
                    # Update cache with current date
                    cls._cache = decrypted_data
                    cls._cache_time = time.time()
                    cls._cache_date = current_date
                    
                    return cls._cache
                else:
                    # Data is not encrypted (fallback)
                    print("⚠️  Warning: Received unencrypted data")
                    cls._cache = raw_data
                    cls._cache_time = time.time()
                    cls._cache_date = current_date
                    
                    return cls._cache
            else:
                raise Exception(response.get('message', 'Unknown error'))
        
        except Exception as e:
            raise Exception(f"Error fetching/decrypting configs for date {current_date}: {str(e)}")
    
    @classmethod
    def clear_cache(cls):
        """Clear the configuration cache securely"""
        if cls._cache:
            cls._cache.clear()
        cls._cache = {}
        cls._cache_time = 0
        cls._cache_date = ""
        print("🧹 Cache cleared")
    
    @classmethod
    def refresh_configs(cls) -> bool:
        """Force refresh configurations from server"""
        try:
            current_date = date.today().isoformat()
            print(f"🔄 Force refreshing configs for date: {current_date}")
            
            cls.clear_cache()
            
            response = asyncio.run(api_client.get("/chats/api_keys"))
            response = response.standard_response()
            
            if response["success"]:
                # Extract encrypted data from StandardResponse format
                raw_data = response["data"]["configs"]  # Changed from response["data"] to response["data"]["configs"]
                
                if isinstance(raw_data, str):
                    decrypted_data = PureDateEncryption.decrypt_data(raw_data)
                    cls._cache = decrypted_data
                else:
                    cls._cache = raw_data
                
                cls._cache_time = time.time()
                cls._cache_date = current_date
                return True
            else:
                return False
        except Exception as e:
            print(f"❌ Refresh failed: {e}")
            return False
    
    @classmethod
    def is_server_available(cls) -> bool:
        """Check if server is available"""
        try:
            response = asyncio.run(api_client.get("/"))
            return response["success"]
        except Exception:
            return False
    
    @classmethod
    def get_cache_info(cls) -> Dict[str, Any]:
        """Get cache information with date-based encryption details"""
        current_date = date.today().isoformat()
        encryption_info = PureDateEncryption.get_current_date_info()
        
        return {
            "has_cache": bool(cls._cache),
            "config_count": len(cls._cache) if cls._cache else 0,
            "cache_time": cls._cache_time,
            "cache_age_seconds": time.time() - cls._cache_time if cls._cache_time else 0,
            "cache_date": cls._cache_date,
            "current_date": current_date,
            "cache_valid_for_date": cls._cache_date == current_date,
            "encryption": encryption_info
        }
    
    @classmethod
    def get_encryption_info(cls) -> Dict[str, Any]:
        """Get detailed encryption information"""
        return PureDateEncryption.get_current_date_info()

# Simple convenience functions - Use these for easy access
def get_llm_config(config_name: str) -> Dict[str, Any]:
    """Get LLM config - Simple function"""
    return LLMConfigManager.get_config(config_name)

def list_configs() -> list:
    """List available configs - Simple function"""
    return LLMConfigManager.get_available_configs()

def clear_llm_cache():
    """Clear LLM config cache securely"""
    LLMConfigManager.clear_cache()

def refresh_llm_configs() -> bool:
    """Refresh configs from server"""
    return LLMConfigManager.refresh_configs()

def get_cache_info() -> Dict[str, Any]:
    """Get cache information"""
    return LLMConfigManager.get_cache_info()

def get_encryption_info() -> Dict[str, Any]:
    """Get encryption strength information"""
    return LLMConfigManager.get_encryption_info()

def is_server_available() -> bool:
    """Check if server is available"""
    return LLMConfigManager.is_server_available()

def get_current_date_key() -> str:
    """Get current date being used for encryption"""
    return date.today().isoformat()

# Context manager for auto-cleanup
class LLMConfigContext:
    """Context manager that auto-clears cache after use"""
    
    def __init__(self, config_name: str):
        self.config_name = config_name
        self.config = None
    
    def __enter__(self):
        self.config = get_llm_config(self.config_name)
        return self.config
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        clear_llm_cache()

# Easy-to-use function with auto-cleanup
def get_llm_config_clean(config_name: str) -> Dict[str, Any]:
    """Get LLM config and automatically clear cache after"""
    try:
        config = get_llm_config(config_name)
        return config
    finally:
        clear_llm_cache()

# Default usage examples
# if __name__ == "__main__":
#     current_date = date.today().isoformat()
    
#     print("🚀 LLM Config Manager - Pure Date-Based Encryption")
#     print(f"📅 Current date key: {current_date}")
#     print("🔑 No stored keys - generated from current date only!")
    
#     try:
#         # 1. Show current date key being used
#         print(f"\n1. Current date key information:")
#         print(f"📅 Date key: {get_current_date_key()}")
#         encryption = get_encryption_info()
#         print(f"🔐 Algorithm: {encryption['algorithm']}")
#         print(f"🔄 Rotation: {encryption['key_rotation']}")
#         print(f"📍 Key source: {encryption['key_source']}")
        
#         # 2. Get config with date-based decryption
#         print(f"\n2. Getting config with date-based decryption:")
#         config = LLMConfigManager.get_config("gpt_4_1_mini")
#         print(f"✅ Config retrieved successfully")
        
#         # 3. List all available configs
#         print(f"\n3. Available configurations:")
#         configs = LLMConfigManager.get_available_configs()
#         print(f"📋 Available: {configs}")
        
#         # 4. Check cache validity for current date
#         print(f"\n4. Cache information:")
#         info = get_cache_info()
#         print(f"📊 Cache configs: {info['config_count']}")
#         print(f"📅 Cache date: {info['cache_date']}")
#         print(f"📅 Current date: {info['current_date']}")
#         print(f"✅ Cache valid for today: {info['cache_valid_for_date']}")
        
#         # 5. Context manager with auto-cleanup
#         print(f"\n5. Context manager with auto-cleanup:")
#         with LLMConfigContext("gpt4_mini") as config:
#             print(f"🧹 Config in context (will auto-clear)")
        
#         # 6. Test cache behavior after date change simulation
#         print(f"\n6. Cache behavior:")
#         print(f"💡 Cache automatically invalidates when date changes")
#         print(f"💡 Each day gets fresh encryption keys")
#         print(f"💡 No manual key management required")
        
#         print(f"\n✅ All examples completed successfully!")
#         print(f"🔐 Pure date-based encryption active")
#         print(f"📅 Keys rotate automatically at midnight")
        
#     except Exception as e:
#         print(f"❌ Error: {e}")
#         print(f"\n💡 Troubleshooting:")
#         print(f"   1. Check server is running: /encryption-status")
#         print(f"   2. Verify server uses same date: {current_date}")
#         print(f"   3. Check timezone sync between server and client")
#         print(f"   4. Test server date key: /test-date-key")
        
#         # Show additional debug info
#         try:
#             info = get_cache_info()
#             print(f"   5. Cache date: {info.get('cache_date', 'None')}")
#             print(f"   6. Current date: {info.get('current_date', 'None')}")
#         except:
#             pass