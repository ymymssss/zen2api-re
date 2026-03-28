import asyncio
from abc import abstractmethod
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import unquote, urlparse

import orjson
import toml

from app.core.config import setting
from app.core.logger import logging
from app.core.paths import DATA_ROOT, ensure_runtime_dirs

logger = logging.getLogger(__name__)


class BaseStorage:
    @abstractmethod
    async def init_db(self) -> None: ...

    @abstractmethod
    async def load_tokens(self) -> list: ...

    @abstractmethod
    async def save_tokens(self, data: list) -> None: ...

    @abstractmethod
    async def load_config(self) -> Dict: ...

    @abstractmethod
    async def save_config(self, config: Dict) -> None: ...


class FileStorage(BaseStorage):
    def __init__(self) -> None:
        self.data_dir = DATA_ROOT
        self.token_file = self.data_dir / "token.json"
        self.config_file = self.data_dir / "setting.toml"
        self._token_lock = asyncio.Lock()
        self._config_lock = asyncio.Lock()

    async def init_db(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    async def load_tokens(self) -> list:
        if not self.token_file.exists():
            return []
        async with self._token_lock:
            data = await asyncio.to_thread(self.token_file.read_bytes)
            tokens = orjson.loads(data)
            if tokens is None:
                return []
            if isinstance(tokens, dict):
                return [tokens]
            if isinstance(tokens, list):
                return tokens
            return []

    async def save_tokens(self, data: list) -> None:
        async with self._token_lock:
            await asyncio.to_thread(
                self.token_file.write_bytes,
                orjson.dumps(data, option=orjson.OPT_INDENT_2),
            )

    async def load_config(self) -> Dict:
        async with self._config_lock:
            if not self.config_file.exists():
                return {"global": setting.global_config, "grok": setting.grok_config}
            with open(self.config_file, "r", encoding="utf-8") as f:
                return toml.load(f)

    async def save_config(self, config: Dict) -> None:
        async with self._config_lock:
            with open(self.config_file, "w", encoding="utf-8") as f:
                toml.dump(config, f)
