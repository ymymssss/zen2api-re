"""Configuration management via environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env file if it exists
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


def parse_bool_env(key: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes")


# Server configuration
PORT: int = int(os.environ.get("ZEN2API_PORT", "9015"))
HOST: str = os.environ.get("ZEN2API_HOST", "127.0.0.1")
API_KEY: Optional[str] = os.environ.get("ZEN2API_KEY")

# Upstream URLs
ZEN_UPSTREAM_URL: str = os.environ.get(
    "ZEN2API_ZEN_UPSTREAM_URL",
    "https://opencode.ai/zen/v1/messages"
)
ZEN_MODELS_URL: str = os.environ.get(
    "ZEN2API_ZEN_MODELS_URL",
    "https://opencode.ai/zen/v1/models"
)
ZEN_USER_AGENT: str = os.environ.get(
    "ZEN2API_ZEN_USER_AGENT",
    "Gai-sdk/anthropic/2.0.65 ai-sdk/provider-utils/3.0.21 runtime/bun/1.3.10"
)
ZEN_ANTHROPIC_VERSION: str = os.environ.get(
    "ZEN2API_ZEN_ANTHROPIC_VERSION",
    "2023-06-01"
)

# Kilo upstream URLs
KILO_UPSTREAM_URL: str = os.environ.get(
    "ZEN2API_KILO_UPSTREAM_URL",
    "https://api.kilo.ai/api/openrouter/chat/completions"
)
KILO_MODELS_URL: str = os.environ.get(
    "ZEN2API_KILO_MODELS_URL",
    "https://api.kilo.ai/api/openrouter/models"
)

# Model configuration
DEFAULT_ZEN_FALLBACK_MODELS: list[str] = [
    "minimax-m2.5-free",
    "kilo-auto/free",
    "minimax/minimax-m2.5:free",
    "stepfun/step-3.5-flash:free",
]
ZEN_MODELS: list[str] = os.environ.get(
    "ZEN2API_ZEN_MODELS",
    ",".join(DEFAULT_ZEN_FALLBACK_MODELS)
).split(",")

DEFAULT_KILO_FALLBACK_MODELS: list[str] = []
KILO_MODELS: list[str] = os.environ.get(
    "ZEN2API_KILO_MODELS",
    ",".join(DEFAULT_KILO_FALLBACK_MODELS)
).split(",")

# Model discovery
MODEL_DISCOVERY_ENABLED: bool = parse_bool_env(
    "ZEN2API_MODEL_DISCOVERY_ENABLED", True
)
MODEL_DISCOVERY_TTL_SECONDS: int = int(
    os.environ.get("ZEN2API_MODEL_DISCOVERY_TTL_SECONDS", "3600")
)
MODEL_DISCOVERY_TIMEOUT_SECONDS: int = int(
    os.environ.get("ZEN2API_MODEL_DISCOVERY_TIMEOUT_SECONDS", "30")
)

# Rate limiting
NON_MODAL_RPS: Optional[int] = os.environ.get("ZEN2API_NON_MODAL_RPS")
if NON_MODAL_RPS is not None:
    NON_MODAL_RPS = int(NON_MODAL_RPS)

# Logging
LOG_LEVEL: str = os.environ.get("ZEN2API_LOG_LEVEL", "INFO")
LOG_FILE: Optional[str] = os.environ.get("ZEN2API_LOG_FILE")
LOG_HEALTH_CHECK: bool = parse_bool_env("ZEN2API_LOG_HEALTH_CHECK", False)

# Stats
STATS_FILE: str = os.environ.get("ZEN2API_STATS_FILE", "stats.json")
STATS_LOG_INTERVAL: int = int(
    os.environ.get("ZEN2API_STATS_LOG_INTERVAL", "3600")
)

# Auth
auth_enabled: bool = API_KEY is not None and API_KEY.strip() != ""
