"""Grok token management."""
from __future__ import annotations

import asyncio
import json
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...core.config import setting
from ...core.exception import GrokApiException
from ...core.logger import logger
from ...core.paths import DATA_ROOT, ensure_runtime_dirs
from ...core.proxy_pool import proxy_pool


class TokenType(Enum):
    """Token types."""
    COOKIE = "cookie"
    BEARER = "bearer"


class Token:
    """Represents a Grok API token."""

    def __init__(
        self,
        token: str,
        token_type: TokenType = TokenType.COOKIE,
        is_valid: bool = True,
        cooldown_until: float = 0,
    ):
        self.token = token
        self.token_type = token_type
        self.is_valid = is_valid
        self.cooldown_until = cooldown_until
        self.request_count = 0
        self.success_count = 0
        self.fail_count = 0


class GrokTokenManager:
    """Manages Grok API tokens with rotation and health checking."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not GrokTokenManager._initialized:
            self.token_file = DATA_ROOT / "token.json"
            self._file_lock = asyncio.Lock()
            self._storage = None
            self.token_data = {
                "running": 0,
                "current": 0,
                "total": 0,
                "success": 0,
                "failed": 0,
                "tokens": [],
            }
            self._save_pending = False
            self._save_task = None
            self._shutdown = False
            self._cooldown_counts = {}
            self._request_counter = 0
            self._refresh_lock = asyncio.Lock()
            self._refresh_progress = False
            GrokTokenManager._initialized = True

    def set_storage(self, storage):
        self._storage = storage

    async def init(self):
        ensure_runtime_dirs()
        await self._load_data()
        logger.debug("[Token] Initialized")

    async def _load_data(self):
        if self._storage:
            self.token_data = await self._storage.load_tokens()
        elif self.token_file.exists():
            try:
                def load_sync():
                    try:
                        import portalocker
                        with open(self.token_file, "r", encoding="utf-8") as f:
                            portalocker.lock(f, portalocker.LOCK_SH)
                            data = json.load(f)
                            portalocker.unlock(f)
                            return data
                    except ImportError:
                        with open(self.token_file, "r", encoding="utf-8") as f:
                            return json.load(f)
                self.token_data = await asyncio.to_thread(load_sync)
            except Exception as e:
                logger.warning(f"[Token] Failed to load: {e}")

    async def _save_data(self):
        if self._storage:
            await self._storage.save_tokens(self.token_data)
        else:
            try:
                data = json.dumps(self.token_data, indent=2)
                self.token_file.write_text(data, encoding="utf-8")
            except Exception as e:
                logger.warning(f"[Token] Failed to save: {e}")

    def add_token(self, token, token_type=TokenType.COOKIE):
        self.token_data["tokens"].append({
            "token": token,
            "type": token_type.value,
            "is_valid": True,
            "cooldown_until": 0,
        })
        self.token_data["total"] = len(self.token_data["tokens"])
        self._save_pending = True

    def remove_token(self, token):
        self.token_data["tokens"] = [
            t for t in self.token_data["tokens"] if t["token"] != token
        ]
        self.token_data["total"] = len(self.token_data["tokens"])
        self._save_pending = True

    def get_token(self):
        import time
        now = time.time()
        for token_data in self.token_data["tokens"]:
            if not token_data.get("is_valid", True):
                continue
            if token_data.get("cooldown_until", 0) > now:
                continue
            return Token(
                token=token_data["token"],
                token_type=TokenType(token_data.get("type", "cookie")),
            )
        return None

    def mark_success(self, token):
        self.token_data["success"] = self.token_data.get("success", 0) + 1

    def mark_failed(self, token, cooldown=60):
        import time
        self.token_data["failed"] = self.token_data.get("failed", 0) + 1
        for t in self.token_data["tokens"]:
            if t["token"] == token:
                t["cooldown_until"] = time.time() + cooldown
                break

    def list_tokens(self):
        return self.token_data.get("tokens", [])

    async def refresh_tokens(self):
        async with self._refresh_lock:
            if self._refresh_progress:
                return
            self._refresh_progress = True
            try:
                logger.debug("[Token] Refreshing tokens")
            finally:
                self._refresh_progress = False

    async def start_batch_save(self):
        logger.debug("[Token] Starting batch save")

    async def stop_batch_save(self):
        logger.debug("[Token] Stopping batch save")


# Singleton instance
token_manager = GrokTokenManager()
