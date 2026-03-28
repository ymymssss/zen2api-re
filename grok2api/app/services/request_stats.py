import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

import orjson

from app.core.config import setting
from app.core.logger import logging
from app.core.paths import DATA_ROOT, ensure_runtime_dirs

logger = logging.getLogger(__name__)


class RequestStats:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if RequestStats._initialized:
            return
        RequestStats._initialized = True

        self.file_path = DATA_ROOT / "stats.json"
        self._hourly: Dict = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
        self._daily: Dict = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
        self._models: Dict = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
        self._hourly_keep = 24
        self._daily_keep = 30
        self._cleanup_interval = 3600
        self._cleanup_counter = 0
        self._lock = asyncio.Lock()
        self._loaded = False
        self._save_task = None

    async def init(self) -> None:
        await self._load_data()
        logger.debug("[Stats] Initialized")

    async def _load_data(self) -> None:
        if not self.file_path.exists():
            return

        try:
            data = await asyncio.to_thread(self.file_path.read_bytes)
            content = orjson.loads(data)
            if isinstance(content, dict):
                if "hourly" in content:
                    self._hourly.update(content["hourly"])
                if "daily" in content:
                    self._daily.update(content["daily"])
                if "models" in content:
                    self._models.update(content["models"])
            self._loaded = True
            logger.debug("[Stats] Loaded stats")
        except Exception as e:
            logger.error("[Stats] Error loading stats: %s", e)

    async def _save_data(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hourly": dict(self._hourly),
            "daily": dict(self._daily),
            "models": dict(self._models),
        }
        await asyncio.to_thread(
            self.file_path.write_bytes,
            orjson.dumps(data, option=orjson.OPT_INDENT_2),
        )

    async def record_request(
        self,
        model: str,
        success: bool,
        duration: float = 0,
    ) -> None:
        async with self._lock:
            now = datetime.now()
            hourly_key = now.strftime("%Y-%m-%d %H:00")
            daily_key = now.strftime("%Y-%m-%d")

            status = "success" if success else "failed"

            self._hourly[hourly_key]["total"] += 1
            self._hourly[hourly_key][status] += 1

            self._daily[daily_key]["total"] += 1
            self._daily[daily_key][status] += 1

            self._models[model]["total"] += 1
            self._models[model][status] += 1

            self._cleanup_counter += 1
            if self._cleanup_counter >= 10:
                self._cleanup_counter = 0
                await self._cleanup()
                await self._save_data()

    async def _cleanup(self) -> None:
        now = datetime.now()
        cutoff_hourly = (now - timedelta(hours=self._hourly_keep)).strftime("%Y-%m-%d %H:00")
        cutoff_daily = (now - timedelta(days=self._daily_keep)).strftime("%Y-%m-%d")

        self._hourly = defaultdict(
            lambda: {"total": 0, "success": 0, "failed": 0},
            {k: v for k, v in self._hourly.items() if k >= cutoff_hourly},
        )
        self._daily = defaultdict(
            lambda: {"total": 0, "success": 0, "failed": 0},
            {k: v for k, v in self._daily.items() if k >= cutoff_daily},
        )

    async def get_stats(self) -> Dict:
        return {
            "hourly": dict(self._hourly),
            "daily": dict(self._daily),
            "models": dict(self._models),
        }


request_stats = RequestStats()
