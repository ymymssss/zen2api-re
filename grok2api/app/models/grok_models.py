from enum import Enum
from typing import Dict, Tuple


class TokenType(str, Enum):
    NORMAL = "ssoNormal"
    SUPER = "ssoSuper"


class Token:
    def __init__(self, token_data: Dict = None):
        self.token_data = token_data or {}


GROK_MODELS = {
    "grok-3-fast": {
        "model": "grok-3-fast",
        "cost": "low_cost",
        "type": "grok_model",
        "multiplier": 1,
        "description": "Fast and efficient Grok 3 model",
        "requires_super": False,
        "display_name": "Grok 3 Fast",
        "raw_model_path": "xai/grok-3",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-4-fast": {
        "model": "grok-4-fast",
        "cost": "low_cost",
        "type": "grok_model",
        "multiplier": 1,
        "description": "Fast version of Grok 4 with mini thinking capabilities",
        "requires_super": False,
        "display_name": "Grok 4 Fast",
        "raw_model_path": "xai/grok-4-mini-thinking-tahoe",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-4-fast-expert": {
        "model": "grok-4-fast-expert",
        "cost": "high_cost",
        "type": "grok_model",
        "multiplier": 2,
        "description": "Expert mode of Grok 4 Fast with enhanced reasoning",
        "requires_super": False,
        "display_name": "Grok 4 Fast Expert",
        "raw_model_path": "xai/grok-4-mini-thinking-tahoe",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-4": {
        "model": "grok-4",
        "cost": "high_cost",
        "type": "grok_model",
        "multiplier": 2,
        "description": "Standard Grok 4 model",
        "requires_super": False,
        "display_name": "Grok 4",
        "raw_model_path": "xai/grok-4",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-4-expert": {
        "model": "grok-4-expert",
        "cost": "high_cost",
        "type": "grok_model",
        "multiplier": 3,
        "description": "Full Grok 4 model with expert mode capabilities",
        "requires_super": False,
        "display_name": "Grok 4 Expert",
        "raw_model_path": "xai/grok-4",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-4-heavy": {
        "model": "grok-4-heavy",
        "cost": "high_cost",
        "type": "grok_model",
        "multiplier": 5,
        "description": "Most powerful Grok 4 model with heavy computational capabilities. Requires Super Token for access.",
        "requires_super": True,
        "display_name": "Grok 4 Heavy",
        "raw_model_path": "xai/grok-4-heavy",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-4.1-thinking": {
        "model": "grok-4.1-thinking",
        "cost": "high_cost",
        "type": "grok_model",
        "multiplier": 3,
        "description": "Grok 4.1 model with advanced thinking and tool capabilities",
        "requires_super": False,
        "display_name": "Grok 4.1 Thinking",
        "raw_model_path": "xai/grok-4-1-thinking-1129",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
    "grok-imagine-0.9": {
        "model": "grok-imagine-0.9",
        "cost": "high_cost",
        "type": "grok_model",
        "multiplier": 5,
        "description": "Image and video generation model. Supports text-to-image and image-to-video generation.",
        "requires_super": False,
        "display_name": "Grok Imagine 0.9",
        "raw_model_path": "xai/grok-imagine-0.9",
        "default_temperature": 0.7,
        "default_max_output_tokens": 4096,
        "supported_max_output_tokens": 16384,
        "default_top_p": 0.95,
    },
}


def is_video_model(model: str) -> bool:
    return model == "grok-imagine-0.9"


class Models:
    _MODEL_CONFIG = GROK_MODELS

    @classmethod
    def get(cls, model_name: str) -> Dict:
        return cls._MODEL_CONFIG.get(model_name)

    @classmethod
    def get_all_model_names(cls) -> list:
        return list(cls._MODEL_CONFIG.keys())

    @classmethod
    def is_valid_model(cls, model_name: str) -> bool:
        return model_name in cls._MODEL_CONFIG

    @classmethod
    def get_model_info(cls, model_name: str) -> Dict:
        return cls._MODEL_CONFIG.get(model_name, {})
