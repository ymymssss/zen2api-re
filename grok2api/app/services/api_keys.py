import asyncio
import secrets
from pathlib import Path
from typing import Dict, List, Optional

import orjson

from app.core.config import setting
from app.core.logger import logging
from app.core.paths import DATA_ROOT, ensure_runtime_dirs

logger = logging.getLogger(__name__)


class ApiKeyManager:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if ApiKeyManager._initialized:
            return
        ApiKeyManager._initialized = True

        self.file_path = DATA_ROOT / "api_keys.json"
        self._keys: Dict = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def init(self) -> None:
        await self._load_data()
        logger.debug(" API Keys initialized: %d keys loaded", len(self._keys))

    async def _load_data(self) -> None:
        if not self.file_path.exists():
            logger.debug(" API Key file not found, starting with empty keys")
            self._keys = {}
            return

        try:
            data = await asyncio.to_thread(self.file_path.read_bytes)
            content = orjson.loads(data)
            if isinstance(content, dict):
                self._keys = content
            else:
                self._keys = {}
            self._loaded = True
            logger.debug(" API Keys loaded: %d keys", len(self._keys))
        except Exception as e:
            logger.error(" Error loading API keys: %s", e)
            self._keys = {}

    async def _save_data(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            self.file_path.write_bytes,
            orjson.dumps(self._keys, option=orjson.OPT_INDENT_2),
        )

    @staticmethod
    def generate_key() -> str:
        return "sk-" + secrets.token_urlsafe(32)

    async def create_key(self, name: str = "API Key") -> Dict:
        key = self.generate_key()
        key_info = {
            "key": key,
            "name": name,
            "created_at": __import__("time").time(),
            "is_active": True,
        }
        self._keys[key] = key_info
        await self._save_data()
        logger.debug(" API Key created: %s", name)
        return key_info

    async def delete_key(self, key: str) -> bool:
        if key in self._keys:
            del self._keys[key]
            await self._save_data()
            logger.debug(" API Key deleted")
            return True
        return False

    async def validate_key(self, key: str) -> Optional[Dict]:
        key_info = self._keys.get(key)
        if key_info and key_info.get("is_active", False):
            return key_info
        return None

    async def get_all_keys(self) -> Dict:
        return self._keys.copy()

    async def list_keys(self) -> List[Dict]:
        return list(self._keys.values())


api_key_manager = ApiKeyManager()
