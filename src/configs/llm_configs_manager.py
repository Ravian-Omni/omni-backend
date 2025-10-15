"""LLM configuration manager with date-based encryption.

This module provides secure management of LLM configurations with automatic
date-based AES-256-GCM encryption. Configurations are fetched from the API,
decrypted using daily rotating keys, and cached for performance.
"""
# llm_config_manager.py - Pure date-based encryption (no settings dependency)
import base64
import copy
import hashlib
import json
import time
from datetime import date, datetime, timezone
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.utilities.api_client import api_client
from src.utilities.async_helpers import async_to_sync


class PureDateEncryption:
    """Pure date-based AES-256-GCM encryption with automatic key rotation.

    Provides encryption and decryption using keys derived from the current date.
    Keys automatically rotate daily at midnight UTC, ensuring fresh encryption
    without manual key management.

    Attributes:
        KEY_SIZE: AES key size in bytes (32 = 256 bits).
        IV_SIZE: Initialization vector size in bytes (12 = 96 bits for GCM).
        TAG_SIZE: Authentication tag size in bytes (16 = 128 bits).
        SALT_SIZE: Salt size for key derivation (32 = 256 bits).
    """

    KEY_SIZE = 32  # 256 bits
    IV_SIZE = 12  # 96 bits for GCM
    TAG_SIZE = 16  # 128 bits authentication tag
    SALT_SIZE = 32  # 256 bits salt for key derivation

    @staticmethod
    def _get_date_based_key() -> bytes:
        """Get encryption key based purely on current date.

        Generate a deterministic encryption key using the current UTC date.
        The key is derived using SHA-256 hash of the date combined with a
        fixed salt.

        Returns:
            32-byte encryption key derived from current date.
        """
        # Use current date as primary key (YYYY-MM-DD format)
        # current_date = date.today().isoformat()
        current_date = datetime.now(timezone.utc).date().isoformat()

        # Create deterministic key from date only
        # Using same fixed salt as server ensures compatibility
        fixed_salt = "llm_config_date_encryption_2025"

        # Combine date + fixed salt for master key
        combined = f"{current_date}:{fixed_salt}".encode()
        return hashlib.sha256(combined).digest()

    @staticmethod
    def decrypt_data(encrypted_data: str) -> dict[str, Any]:
        """Decrypt data using current date as key.

        Decrypt AES-256-GCM encrypted data using a key derived from today's date.
        The encrypted data must include salt, IV, authentication tag, and ciphertext.

        Args:
            encrypted_data: Base64-encoded encrypted data blob.

        Returns:
            Decrypted data as dictionary.

        Raises:
            Exception: If decryption fails due to invalid key, corrupted data,
                or authentication failure.
        """
        try:
            current_date = date.today().isoformat()
            print(f"🔓 Client decrypting with date key: {current_date}")

            # Decode base64
            encrypted_blob = base64.b64decode(encrypted_data.encode())

            # Extract components
            salt = encrypted_blob[: PureDateEncryption.SALT_SIZE]
            iv = encrypted_blob[
                PureDateEncryption.SALT_SIZE : PureDateEncryption.SALT_SIZE
                + PureDateEncryption.IV_SIZE
            ]
            tag = encrypted_blob[
                PureDateEncryption.SALT_SIZE
                + PureDateEncryption.IV_SIZE : PureDateEncryption.SALT_SIZE
                + PureDateEncryption.IV_SIZE
                + PureDateEncryption.TAG_SIZE
            ]
            ciphertext = encrypted_blob[
                PureDateEncryption.SALT_SIZE
                + PureDateEncryption.IV_SIZE
                + PureDateEncryption.TAG_SIZE :
            ]

            # Get date-based master key
            master_key = PureDateEncryption._get_date_based_key()

            # Derive decryption key using HKDF
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=PureDateEncryption.KEY_SIZE,
                salt=salt,
                info=b"llm_config_encryption",
                backend=default_backend(),
            )
            decryption_key = hkdf.derive(master_key)

            # Decrypt with AES-256-GCM
            cipher = Cipher(
                algorithms.AES(decryption_key),
                modes.GCM(iv, tag),
                backend=default_backend(),
            )
            decryptor = cipher.decryptor()
            decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()

            # Convert back to dict
            return json.loads(decrypted_data.decode())

        except Exception as e:
            current_date = date.today().isoformat()
            raise Exception(f"Decryption failed with date key {current_date}: {str(e)}")

    @staticmethod
    def get_current_date_info() -> dict[str, Any]:
        """Get information about current date-based encryption.

        Provide detailed information about the encryption configuration,
        including algorithm, key rotation schedule, and security parameters.

        Returns:
            Dictionary containing encryption metadata and configuration details.
        """
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
            "key_expiry": "End of day (00:00 UTC)",
        }


class LLMConfigManager:
    """LLM Configuration Manager with pure date-based encryption.

    Manages LLM configurations with automatic fetching, decryption, and caching.
    Configurations are cached per date and automatically invalidated when the
    date changes.

    Attributes:
        _cache: Dictionary storing decrypted configurations.
        _cache_time: Timestamp of when cache was last updated.
        _cache_date: ISO date string for which cache is valid.
    """

    _cache: dict[str, Any] = {}
    _cache_time: float = 0
    _cache_date: str = ""  # Track which date the cache was created

    @classmethod
    def get_config(cls, config_name: str) -> dict[str, Any]:
        """Get LLM configuration by name.

        Retrieve a specific LLM configuration with automatic fetching and
        decryption if not cached.

        Args:
            config_name: Name of the configuration to retrieve.

        Returns:
            Dictionary containing config_list with the requested configuration.

        Raises:
            ValueError: If config_name is not found in available configurations.
        """
        configs = cls._get_all_configs()

        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(
                f"Config '{config_name}' not found. Available: {available}"
            )

        # config_data = configs[config_name]
        config_data = copy.deepcopy(configs[config_name])
        return {"config_list": [config_data]}

    @classmethod
    def get_available_configs(cls) -> list:
        """Get list of available configuration names.

        Returns:
            List of configuration name strings.
        """
        configs = cls._get_all_configs()
        return list(configs.keys())

    @classmethod
    def _get_all_configs(cls) -> dict[str, Any]:
        """Get all configs with automatic decryption and caching.

        Fetch and decrypt all configurations from the API. Uses date-based cache
        validation to ensure cached data is current for today's date.

        Returns:
            Dictionary mapping configuration names to their settings.

        Raises:
            Exception: If fetching or decrypting configurations fails.
        """
        current_date = date.today().isoformat()

        # Check if cache is valid for current date
        if cls._cache and cls._cache_date == current_date:
            print(f"📋 Using cached configs for date: {current_date}")
            return cls._cache

        # Cache is invalid or from different date - fetch fresh data
        try:
            print(f"🔄 Fetching fresh configs for date: {current_date}")

            response = async_to_sync(api_client.get("/chats/api_keys"))
            response = response.standard_response()

            if response["success"]:
                # Extract encrypted data from StandardResponse format
                raw_data = response["data"][
                    "configs"
                ]  # Changed from response["data"] to response["data"]["configs"]

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
                raise Exception(response.get("message", "Unknown error"))

        except Exception as e:
            raise Exception(
                f"Error fetching/decrypting configs for date {current_date}: {str(e)}"
            )

    @classmethod
    def clear_cache(cls):
        """Clear the configuration cache securely.

        Remove all cached configuration data and reset cache metadata.
        """
        if cls._cache:
            cls._cache.clear()
        cls._cache = {}
        cls._cache_time = 0
        cls._cache_date = ""
        print("🧹 Cache cleared")

    @classmethod
    def refresh_configs(cls) -> bool:
        """Force refresh configurations from server.

        Clear cache and fetch fresh configurations from the API regardless
        of current cache state.

        Returns:
            True if refresh was successful, False otherwise.
        """
        try:
            current_date = date.today().isoformat()
            print(f"🔄 Force refreshing configs for date: {current_date}")

            cls.clear_cache()

            response = async_to_sync(api_client.get("/chats/api_keys"))
            response = response.standard_response()

            if response["success"]:
                # Extract encrypted data from StandardResponse format
                raw_data = response["data"][
                    "configs"
                ]  # Changed from response["data"] to response["data"]["configs"]

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
        """Check if server is available.

        Test connectivity to the configuration API server.

        Returns:
            True if server is reachable and responding, False otherwise.
        """
        try:
            response = async_to_sync(api_client.get("/"))
            return response["success"]
        except Exception:
            return False

    @classmethod
    def get_cache_info(cls) -> dict[str, Any]:
        """Get cache information with date-based encryption details.

        Provide comprehensive information about cache state, validity, and
        encryption configuration.

        Returns:
            Dictionary containing cache metadata and encryption details.
        """
        current_date = date.today().isoformat()
        encryption_info = PureDateEncryption.get_current_date_info()

        return {
            "has_cache": bool(cls._cache),
            "config_count": len(cls._cache) if cls._cache else 0,
            "cache_time": cls._cache_time,
            "cache_age_seconds": (
                time.time() - cls._cache_time if cls._cache_time else 0
            ),
            "cache_date": cls._cache_date,
            "current_date": current_date,
            "cache_valid_for_date": cls._cache_date == current_date,
            "encryption": encryption_info,
        }

    @classmethod
    def get_encryption_info(cls) -> dict[str, Any]:
        """Get detailed encryption information.

        Returns:
            Dictionary with encryption algorithm, key sizes, and security details.
        """
        return PureDateEncryption.get_current_date_info()


# Simple convenience functions - Use these for easy access
def get_llm_config(config_name: str) -> dict[str, Any]:
    """Get LLM configuration by name.

    Convenience function for retrieving LLM configurations.

    Args:
        config_name: Name of the configuration to retrieve.

    Returns:
        Dictionary containing config_list with the configuration.
    """
    return LLMConfigManager.get_config(config_name)


def list_configs() -> list:
    """List available configuration names.

    Returns:
        List of available configuration name strings.
    """
    return LLMConfigManager.get_available_configs()


def clear_llm_cache():
    """Clear LLM configuration cache securely.

    Remove all cached configurations and reset cache metadata.
    """
    LLMConfigManager.clear_cache()


def refresh_llm_configs() -> bool:
    """Refresh configurations from server.

    Force fetch fresh configurations from the API.

    Returns:
        True if refresh was successful, False otherwise.
    """
    return LLMConfigManager.refresh_configs()


def get_cache_info() -> dict[str, Any]:
    """Get cache information and status.

    Returns:
        Dictionary containing cache metadata and encryption details.
    """
    return LLMConfigManager.get_cache_info()


def get_encryption_info() -> dict[str, Any]:
    """Get encryption configuration details.

    Returns:
        Dictionary with encryption algorithm, key sizes, and security details.
    """
    return LLMConfigManager.get_encryption_info()


def is_server_available() -> bool:
    """Check if configuration server is available.

    Returns:
        True if server is reachable, False otherwise.
    """
    return LLMConfigManager.is_server_available()


def get_current_date_key() -> str:
    """Get current date being used for encryption.

    Returns:
        ISO format date string (YYYY-MM-DD).
    """
    return date.today().isoformat()


# Context manager for auto-cleanup
class LLMConfigContext:
    """Context manager that auto-clears cache after use.

    Automatically clears the configuration cache when exiting the context,
    ensuring sensitive configuration data is not kept in memory longer than needed.

    Attributes:
        config_name: Name of the configuration to retrieve.
        config: Retrieved configuration dictionary.

    Example:
        >>> with LLMConfigContext("gpt4_mini") as config:
        ...     print(config)
    """

    def __init__(self, config_name: str):
        """Initialize context manager.

        Args:
            config_name: Name of the configuration to retrieve.
        """
        self.config_name = config_name
        self.config = None

    def __enter__(self):
        """Enter context and retrieve configuration.

        Returns:
            Configuration dictionary.
        """
        self.config = get_llm_config(self.config_name)
        return self.config

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and clear cache.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.
        """
        clear_llm_cache()


# Easy-to-use function with auto-cleanup
def get_llm_config_clean(config_name: str) -> dict[str, Any]:
    """Get LLM config and automatically clear cache after.

    Convenience function that retrieves a configuration and immediately clears
    the cache to avoid keeping sensitive data in memory.

    Args:
        config_name: Name of the configuration to retrieve.

    Returns:
        Dictionary containing config_list with the configuration.
    """
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
