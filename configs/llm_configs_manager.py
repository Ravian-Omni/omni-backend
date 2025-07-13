from typing import Dict, Any
from dataclasses import dataclass
import os
from configs.settings import settings

@dataclass
class LLMConfig:
    """Simple LLM configuration container"""
    model: str
    api_key: str = None
    api_type: str = None
    base_url: str = None
    api_version: str = None
    temperature: float = None
    max_tokens: int = None
    reasoning_effort: str = None
    # Add any other common parameters here
    
    def to_autogen_format(self) -> Dict[str, Any]:
        """Convert to AutoGen-compatible format"""
        config = {k: v for k, v in self.__dict__.items() if v is not None}
        return {"config_list": [config]}

class LLMConfigManager:
    
    @classmethod
    def _get_current_api_keys(cls) -> Dict[str, str]:
        """Get current API keys from settings (evaluated at runtime)"""
        return {
            "azure_api_key": settings.AZURE_OPENAI_API_KEY,
            "openai_api_key": settings.OPENAI_API_KEY,
            "together_api_key": settings.TOGETHER_API_KEY,
            "anthropic_api_key": settings.ANTHROPIC_API_KEY,
            "azure_o3_api_key": settings.AZURE_OPENAI_API_KEY_O3
        }
    
    @classmethod
    def get_config(cls, config_name: str) -> Dict[str, Any]:
        """Get predefined configuration by name"""
        # Get fresh API keys each time
        api_keys = cls._get_current_api_keys()
        
        configs = {
            # Azure Configurations
            "gpt4_mini": LLMConfig(
                model="gpt-4o-mini",
                api_key=api_keys["azure_api_key"],
                api_type="azure",
                base_url="https://newton-aoi.openai.azure.com/",
                api_version="2024-08-01-preview",
                temperature=0.15
            ),
            
            "gpt4o": LLMConfig(
                model="gpt-4o",
                api_key=api_keys["azure_api_key"],
                api_type="azure",
                base_url="https://newton-aoi.openai.azure.com/",
                api_version="2024-08-01-preview",
            ),
            
            # Anthropic Configurations
            "claude-3-7-sonnet-20250219": LLMConfig(
                model="claude-3-7-sonnet-20250219",
                api_key=api_keys["anthropic_api_key"],
                api_type="anthropic"
            ),
            
            # Azure O3 Configuration
            "o3-mini-reason-high": LLMConfig(
                model="o3-mini",
                api_key=api_keys["azure_o3_api_key"],
                api_type="azure",
                base_url="https://newton-ai-123.cognitiveservices.azure.com/",
                api_version="2025-01-01-preview",
                # reasoning_effort="high"
            ),
            
            # Together AI Configurations
            "deepseek": LLMConfig(
                model="deepseek-ai/DeepSeek-V3",
                api_key=api_keys["together_api_key"],
                api_type="together"
            ),
            
            "image_together": LLMConfig(
                model="black-forest-labs/FLUX.1-dev",
                api_key=api_keys["together_api_key"],
            ),
            
            # OpenAI Configurations
            "gpt_4_1_mini": LLMConfig(
                model="gpt-4.1-mini-2025-04-14",
                api_key=api_keys["openai_api_key"],
            ),
            
            # Commented configurations for reference
            # "gpt_4_1_mini_azure": LLMConfig(
            #     model="gpt-4.1-mini",
            #     api_key=api_keys["azure_api_key"],
            #     api_type="azure",
            #     base_url="https://newton-aoi.openai.azure.com/",
            #     api_version="2025-01-01-preview"
            # ),
        }
        
        if config_name not in configs:
            available_configs = list(configs.keys())
            raise ValueError(f"Unknown config: {config_name}. Available configs: {available_configs}")
            
        return configs[config_name].to_autogen_format()
    
    @classmethod
    def create_custom_config(cls, **kwargs) -> Dict[str, Any]:
        """Create one-off configurations"""
        return LLMConfig(**kwargs).to_autogen_format()
    
    @classmethod
    def get_available_configs(cls) -> list:
        """Get list of all available configuration names"""
        # Get fresh API keys to build config list
        api_keys = cls._get_current_api_keys()
        
        configs = [
            "gpt4_mini",
            "gpt4o", 
            "claude-3-7-sonnet-20250219",
            "o3-mini-reason-high",
            "deepseek",
            "gpt_4_1_mini",
            "image_together"
        ]
        
        return configs
    
    @classmethod
    def get_config_info(cls, config_name: str) -> Dict[str, Any]:
        """Get configuration info without API keys for debugging"""
        api_keys = cls._get_current_api_keys()
        
        # Create a safe version that shows if keys are available
        safe_api_keys = {
            key: "SET" if value else "NOT_SET" 
            for key, value in api_keys.items()
        }
        
        try:
            config = cls.get_config(config_name)
            model_info = config["config_list"][0]
            
            return {
                "config_name": config_name,
                "model": model_info.get("model"),
                "api_type": model_info.get("api_type"),
                "base_url": model_info.get("base_url"),
                "api_version": model_info.get("api_version"),
                "temperature": model_info.get("temperature"),
                "api_key_status": safe_api_keys,
                "has_api_key": bool(model_info.get("api_key"))
            }
        except ValueError as e:
            return {"error": str(e)}
    
    @classmethod
    def test_api_keys(cls) -> Dict[str, str]:
        """Test which API keys are currently set"""
        api_keys = cls._get_current_api_keys()
        return {
            key: "SET" if value else "NOT_SET" 
            for key, value in api_keys.items()
        }

# Convenience functions for common operations
def get_llm_config(config_name: str) -> Dict[str, Any]:
    """Convenience function to get LLM configuration"""
    return LLMConfigManager.get_config(config_name)

def create_custom_llm_config(**kwargs) -> Dict[str, Any]:
    """Convenience function to create custom LLM configuration"""
    return LLMConfigManager.create_custom_config(**kwargs)

def list_available_configs() -> list:
    """Convenience function to list available configurations"""
    return LLMConfigManager.get_available_configs()

def check_api_keys() -> Dict[str, str]:
    """Convenience function to check API key status"""
    return LLMConfigManager.test_api_keys()

# Example usage and testing
if __name__ == "__main__":
    # Test API key status
    print("API Key Status:")
    print(LLMConfigManager.test_api_keys())
    
    # Test getting a configuration
    try:
        config = LLMConfigManager.get_config("gpt4_mini")
        print(f"\nGPT4 Mini Config: {config}")
    except Exception as e:
        print(f"Error getting config: {e}")
    
    # Test configuration info
    print(f"\nConfig Info: {LLMConfigManager.get_config_info('gpt4_mini')}")
    
    # List available configurations
    print(f"\nAvailable Configs: {LLMConfigManager.get_available_configs()}")

# Example of how to modify an existing configuration
def modify_config_example():
    """Example of how to modify an existing configuration"""
    # Get base configuration
    base_config = LLMConfigManager.get_config("gpt4_mini")
    
    # Modify the configuration
    modified_config = base_config["config_list"][0].copy()
    modified_config.update({
        "temperature": 0.5,
        "max_tokens": 2000
    })
    
    # Return modified configuration in AutoGen format
    return {"config_list": [modified_config]}