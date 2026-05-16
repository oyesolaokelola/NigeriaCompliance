# workflow/config.py
"""
Configuration management for the NigeriaCompliance workflow.

This module handles loading configuration from environment variables
for the multimodal parser and other workflow components.
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path


class Config:
    """Configuration loader for workflow components."""
    
    @staticmethod
    def load_multimodal_parser_config() -> Dict[str, Any]:
        """
        Load multimodal parser configuration from environment variables.
        
        Returns:
            Dictionary containing parser configuration
        """
        config = {
            "model_provider": os.environ.get("MULTIMODAL_PARSER_PROVIDER", "openai"),
            "model": os.environ.get("MULTIMODAL_PARSER_MODEL", "gpt-4o"),
            "reasoning_effort": os.environ.get("MULTIMODAL_PARSER_REASONING_EFFORT", "low"),
            "merge_table": os.environ.get("MULTIMODAL_PARSER_MERGE_TABLE", "true").lower() == "true",
            "create_html": os.environ.get("MULTIMODAL_PARSER_CREATE_HTML", "true").lower() == "true",
            "additional_instructions": os.environ.get("MULTIMODAL_PARSER_ADDITIONAL_INSTRUCTIONS", ""),
        }
        
        # Validate configuration
        if config["model_provider"] not in ["openai", "anthropic", "google"]:
            raise ValueError(f"Invalid model_provider: {config['model_provider']}")
        
        if config["reasoning_effort"] not in ["low", "medium", "high"]:
            raise ValueError(f"Invalid reasoning_effort: {config['reasoning_effort']}")
        
        return config
    
    @staticmethod
    def get_api_key(provider: str) -> Optional[str]:
        """
        Get API key for a specific provider.
        
        Args:
            provider: Provider name ("openai", "anthropic", or "google")
            
        Returns:
            API key string or None if not found
        """
        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY"
        }
        
        env_var = env_var_map.get(provider.lower())
        if env_var:
            return os.environ.get(env_var)
        return None
    
    @staticmethod
    def validate_parser_config(config: Dict[str, Any]) -> bool:
        """
        Validate that the parser configuration has all required API keys.
        
        Args:
            config: Parser configuration dictionary
            
        Returns:
            True if configuration is valid, False otherwise
        """
        provider = config.get("model_provider", "openai")
        api_key = Config.get_api_key(provider)
        
        if not api_key:
            return False
        
        return True
    
    @staticmethod
    def get_repository_path() -> Path:
        """Get the repository directory path."""
        return Path(__file__).resolve().parent.parent
    
    @staticmethod
    def get_templates_path() -> Path:
        """Get the templates directory path."""
        return Config.get_repository_path() / "templates"
    
    @staticmethod
    def get_output_path() -> Path:
        """Get the output directory path."""
        return Config.get_repository_path() / "output"
