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
    _shared_config = {
        "azure_api_key": settings.AZURE_OPENAI_API_KEY,
        "azure_base_url": "https://newton-aoi.openai.azure.com/",
        "azure_api_version": "2024-08-01-preview",
        "openai_api_key": settings.OPENAI_API_KEY,
        "anthropic_api_key":settings.ANTHROPIC_API_KEY
    }
    
    @classmethod
    def get_config(cls, config_name: str) -> Dict[str, Any]:
        """Get predefined configuration by name"""
        configs = {
            # Azure Configurations
            "gpt4_mini": LLMConfig(
                model="gpt-4o-mini",
                api_key=cls._shared_config["azure_api_key"],
                api_type="azure",
                base_url=cls._shared_config["azure_base_url"],
                api_version=cls._shared_config["azure_api_version"],
                temperature=0.15
            ),
            
            "gpt4o": LLMConfig(
                model="gpt-4o",
                api_key=cls._shared_config["azure_api_key"],
                api_type="azure",
                base_url=cls._shared_config["azure_base_url"],
                api_version=cls._shared_config["azure_api_version"],
            ),
            # OpenAI Configurations
            "claude-3-7-sonnet-20250219": LLMConfig(
                model="claude-3-7-sonnet-20250219",
                api_key=cls._shared_config["anthropic_api_key"],
                api_type="anthropic"
            ),
            
            "o3-mini-reason-high": LLMConfig(
                model="o3-mini",
                api_key=settings.AZURE_OPENAI_API_KEY_O3,
                api_type= "azure",
                base_url= "https://newton-ai-123.cognitiveservices.azure.com/",
                api_version= "2025-01-01-preview",
                # reasoning_effort="high"
            ),
            "deepseek": LLMConfig(
                model="deepseek-ai/DeepSeek-V3",
                api_key="06db08babf63e2c871ca8b7709d82f753728e7144e1e32d22b1469b0238a8331",
                api_type="together"
            ),
            "gpt_4_1_mini": LLMConfig(
                model="gpt-4.1-mini-2025-04-14",
                api_key=cls._shared_config["openai_api_key"],
            ),
        
            # Add other configurations as needed...
        }
        
        if config_name not in configs:
            raise ValueError(f"Unknown config: {config_name}")
            
        return configs[config_name].to_autogen_format()
    
    @classmethod
    def create_custom_config(cls, **kwargs) -> Dict[str, Any]:
        """Create one-off configurations"""
        return LLMConfig(**kwargs).to_autogen_format()
    

# Create custom configuration on-the-fly
# custom_config = LLMConfigManager.create_custom_config(
#     model="special-model",
#     api_key="custom-key",
#     temperature=0.3,
#     max_tokens=2000
# )

# # Modify an existing configuration
# base_config = LLMConfigManager.get_config("gpt4_mini")
# base_config
# modified_config = base_config["config_list"][0].copy()
# modified_config.update({"temperature": 0.5})