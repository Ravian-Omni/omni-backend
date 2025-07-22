from typing import Dict, Any
import asyncio
import time
from utilities.api_client import api_client

class LLMConfigManager:
    """LLM Configuration Manager (Class-based methods)"""
    
    _cache: Dict[str, Any] = {}
    _cache_time: float = 0
    
    @classmethod
    def get_config(cls, config_name: str) -> Dict[str, Any]:
        """Get LLM configuration by name"""
        configs = cls._get_all_configs()
        
        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(f"Config '{config_name}' not found. Available: {available}")
        
        config_data = configs[config_name]
        return {"config_list": [config_data]}
    
    @classmethod
    def get_available_configs(cls) -> list:
        """Get list of available configuration names"""
        configs = cls._get_all_configs()
        return list(configs.keys())
    
    @classmethod
    def _get_all_configs(cls) -> Dict[str, Any]:
        """Get all configs - use cache first, API only if cache is empty"""
        
        # Return cached data if available
        if cls._cache:
            return cls._cache
        
        # Only call API if cache is empty
        try:
            response = asyncio.run(api_client.get("/chats/api_keys"))
            response = response.standard_response()
            if response["success"]:
                cls._cache = response["data"]
                cls._cache_time = time.time()
                return cls._cache
            else:
                raise Exception(response.get('message', 'Unknown error'))
        except Exception as e:
            # Return empty dict if API call fails
            raise Exception(f"Error fetching configs: {str(e)}")
    
    @classmethod
    def clear_cache(cls):
        """Clear the configuration cache"""
        cls._cache = {}
        cls._cache_time = 0
    
    @classmethod
    def refresh_configs(cls) -> bool:
        """Force refresh configurations from server (ignores cache)"""
        try:
            response = asyncio.run(api_client.get("/chats/api_keys"))
            response = response.standard_response()
            
            if response["success"]:
                cls._cache = response["data"]
                cls._cache_time = time.time()
                return True
            else:
                return False
        except Exception:
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
        """Get cache information"""
        return {
            "has_cache": bool(cls._cache),
            "config_count": len(cls._cache) if cls._cache else 0,
            "cache_time": cls._cache_time,
            "cache_age_seconds": time.time() - cls._cache_time if cls._cache_time else 0
        }

# Remove singleton instance since we're using classmethods
# llm_config_manager = LLMConfigManager()

# Simple convenience functions (optional - you can use class methods directly)
def get_llm_config(config_name: str) -> Dict[str, Any]:
    """Get LLM config"""
    return LLMConfigManager.get_config(config_name)

def list_configs() -> list:
    """List available configs"""
    return LLMConfigManager.get_available_configs()

def clear_llm_cache():
    """Clear LLM config cache"""
    LLMConfigManager.clear_cache()

def refresh_llm_configs() -> bool:
    """Refresh configs from server"""
    return LLMConfigManager.refresh_configs()

def get_cache_info() -> Dict[str, Any]:
    """Get cache information"""
    return LLMConfigManager.get_cache_info()

def is_server_available() -> bool:
    """Check if server is available"""
    return LLMConfigManager.is_server_available()

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

# Usage Examples:
# if __name__ == "__main__":
#     # Direct class usage (this is what you wanted!)
#     config = LLMConfigManager.get_config("gpt_4_1_mini")
#     print(f"Config: {config}")
    
#     # List available configs
#     available = LLMConfigManager.get_available_configs()
#     print(f"Available configs: {available}")
    
#     # Check cache info
#     info = LLMConfigManager.get_cache_info()
#     print(f"Cache info: {info}")
    
#     # Clear cache
#     LLMConfigManager.clear_cache()
    
#     # Check cache info again
#     info = LLMConfigManager.get_cache_info()
#     print(f"Cache info after clear: {info}")
    
#     # Refresh configs
#     success = LLMConfigManager.refresh_configs()
#     print(f"Refresh successful: {success}")
    
#     # Check server availability
#     server_ok = LLMConfigManager.is_server_available()
#     print(f"Server available: {server_ok}")
    
#     # You can still use convenience functions if you prefer
#     config2 = get_llm_config("claude-3-7-sonnet-20250219")
#     print(f"Config via function: {config2}")
    
#     # Context manager still works
#     with LLMConfigContext("gpt4_mini") as config:
#         print(f"Using config in context: {config}")
    
#     # Auto-cleanup usage
#     config3 = get_llm_config_clean("deepseek")
#     print(f"Config with auto-cleanup: {config3}")