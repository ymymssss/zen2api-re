import asyncio
from typing import Optional

import aiohttp

from app.core.config import setting
from app.core.logger import logging
from app.core.paths import TEMP_ROOT, ensure_runtime_dirs

logger = logging.getLogger(__name__)

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


class CacheService:
    def __init__(self, cache_type: str = "image", timeout: float = 30.0) -> None:
        self.cache_type = cache_type
        self.timeout = timeout
        self.cache_dir = TEMP_ROOT / cache_type
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_lock = asyncio.Lock()

    def _get_path(self, file_path: str) -> object:
        file_path = file_path.lstrip("/").replace("/", "_")
        return self.cache_dir / file_path

    def _log(self, level: str, msg: str, *args) -> None:
        getattr(logger, level)(f"[Cache] {msg}", *args)

    def _build_headers(self, auth_token: str = None, cf_clearance: str = None) -> dict:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://grok.com/",
        }

        grok_config = setting.grok_config
        if cf_clearance:
            headers["Cookie"] = f"cf_clearance={cf_clearance}"
        elif grok_config.get("cf_clearance"):
            headers["Cookie"] = f"cf_clearance={grok_config['cf_clearance']}"

        return headers

    async def get(
        self,
        url: str,
        auth_token: str = None,
        cf_clearance: str = None,
        force_refresh: bool = False,
    ) -> Optional[bytes]:
        if not url.startswith("https://assets.grok.com"):
            return None

        path = self._get_path(url.replace("https://assets.grok.com/", ""))

        if not force_refresh and path.exists():
            self._log("debug", "Cache hit: %s", path)
            return await asyncio.to_thread(path.read_bytes)

        headers = self._build_headers(auth_token, cf_clearance)

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        path.parent.mkdir(parents=True, exist_ok=True)
                        await asyncio.to_thread(path.write_bytes, data)
                        self._log("debug", "Cached: %s", path)
                        return data
                    elif resp.status in setting.grok_config.get("retry_status_codes", [403, 429, 500]):
                        self._log("warning", "Retryable status %d for %s", resp.status, url)
                        return None
                    else:
                        self._log("error", "Failed to fetch %s: HTTP %d", url, resp.status)
                        return None
        except Exception as e:
            self._log("error", "Error fetching %s: %s", url, e)
            return None


image_cache_service = CacheService("image")
video_cache_service = CacheService("video", timeout=60.0)
