import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Deque, Dict, List

import orjson

from app.core.config import setting
from app.core.logger import logging
from app.core.paths import DATA_ROOT, ensure_runtime_dirs

logger = logging.getLogger(__name__)


@dataclass
class RequestLog:
    time: float
    timestamp: str
    model: str
    duration: float
    status: str
    key_name: str
    token_suffix: str
    error: str = ""


class RequestLogger:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_len: int = 10000) -> None:
        if RequestLogger._initialized:
            return
        RequestLogger._initialized = True

        self.file_path = DATA_ROOT / "logs.json"
        self._logs: Deque[Dict] = deque(maxlen=max_len)
        self._lock = asyncio.Lock()
        self._loaded = False
        self._save_task = None

    async def init(self) -> None:
        await self._load_data()
        logger.debug("[Logger] Initialized with %d logs", len(self._logs))

    async def _load_data(self) -> None:
        if not self.file_path.exists():
            self._logs.clear()
            return

        try:
            data = await asyncio.to_thread(self.file_path.read_bytes)
            content = orjson.loads(data)
            if isinstance(content, list):
                self._logs.clear()
                self._logs.extend(content[-10000:])
            self._loaded = True
            logger.debug("[Logger] Loaded %d logs", len(self._logs))
        except Exception as e:
            logger.error("[Logger] Error loading logs: %s", e)
            self._logs.clear()

    async def _save_data(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            self.file_path.write_bytes,
            orjson.dumps(list(self._logs), option=orjson.OPT_INDENT_2),
        )

    async def add_log(self, log: RequestLog) -> None:
        async with self._lock:
            self._logs.append(asdict(log))
            if len(self._logs) % 10 == 0:
                await self._save_data()

    async def get_logs(self, limit: int = 100) -> List[Dict]:
        return list(self._logs)[-limit:]

    async def clear_logs(self) -> None:
        async with self._lock:
            self._logs.clear()
            await self._save_data()


request_logger = RequestLogger()
