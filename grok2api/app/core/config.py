import os
from pathlib import Path
from typing import Dict, Optional

import toml

from app.core.paths import DATA_ROOT, ensure_runtime_dirs


DEFAULT_GLOBAL: Dict = {
    "api_key": "",
    "proxy_url": "",
    "proxy_pool_url": "",
    "proxy_pool_interval": 60,
    "cache_proxy_url": "",
    "cf_clearance": "",
    "x_statsig_id": "",
    "dynamic_statsig": True,
    "filtered_tags": "xai:artifact,xai:tool_usage_card",
    "show_thinking": False,
    "temporary": False,
    "max_upload_concurrency": 3,
    "max_request_concurrency": 10,
    "stream_first_response_timeout": 30,
    "stream_chunk_timeout": 30,
    "stream_total_timeout": 300,
    "retry_status_codes": [403, 429, 500, 502, 503],
    "base_url": "http://localhost:8000",
    "log_level": "INFO",
    "image_mode": "upload",
    "admin_password": "admin",
    "admin_username": "admin",
    "image_cache_max_size_mb": 500,
    "video_cache_max_size_mb": 1000,
    "batch_save_interval": 30,
    "batch_save_threshold": 10,
}

DEFAULT_GROK: Dict = {
    "api_key": "",
    "proxy_url": "",
    "proxy_pool_url": "",
    "proxy_pool_interval": 60,
    "cache_proxy_url": "",
    "cf_clearance": "",
    "x_statsig_id": "",
    "dynamic_statsig": True,
    "filtered_tags": "xai:artifact,xai:tool_usage_card",
    "show_thinking": False,
    "temporary": False,
    "max_upload_concurrency": 3,
    "max_request_concurrency": 10,
    "stream_first_response_timeout": 30,
    "stream_chunk_timeout": 30,
    "stream_total_timeout": 300,
    "retry_status_codes": [403, 429, 500, 502, 503],
    "base_url": "http://localhost:8000",
    "log_level": "INFO",
    "image_mode": "upload",
    "admin_password": "admin",
    "admin_username": "admin",
    "image_cache_max_size_mb": 500,
    "video_cache_max_size_mb": 1000,
    "batch_save_interval": 30,
    "batch_save_threshold": 10,
}


class ConfigManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self.config_path = DATA_ROOT / "setting.toml"
        self._storage = None
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self._create_default()

    def _create_default(self) -> None:
        config = {
            "global": DEFAULT_GLOBAL.copy(),
            "grok": DEFAULT_GROK.copy(),
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            toml.dump(config, f)

    def load(self) -> Dict:
        if not self.config_path.exists():
            self._create_default()
        with open(self.config_path, "r", encoding="utf-8") as f:
            return toml.load(f)

    def save(self, config: Dict) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            toml.dump(config, f)

    @property
    def global_config(self) -> Dict:
        return self.load().get("global", {})

    @property
    def grok_config(self) -> Dict:
        return self.load().get("grok", {})

    def get(self, key: str, default=None):
        return self.global_config.get(key, default)


setting = ConfigManager()


def get_dynamic_headers(grok_config: Optional[Dict] = None) -> Dict:
    if grok_config is None:
        grok_config = setting.grok_config

    cf_clearance = grok_config.get("cf_clearance", "")

    proxy = grok_config.get("proxy_url", "")
    if proxy and proxy.startswith("sock5/socks5"):
        proxy = proxy.replace("sock5/socks5", "socks5h://", 1)

    return {
        "cf_clearance": cf_clearance,
        "proxy": proxy,
    }
