import asyncio
from typing import List, Optional

import aiohttp

from app.core.logger import logging

logger = logging.getLogger(__name__)


class ProxyPool:
    def __init__(
        self,
        proxy_url: str = "",
        proxy_pool_url: str = "",
        proxy_pool_interval: int = 60,
    ) -> None:
        self._pool_url = proxy_pool_url
        self._static_proxy = proxy_url
        self._current_proxy = proxy_url
        self._last_fetch_time = 0
        self._fetch_interval = proxy_pool_interval
        self._enabled = bool(proxy_pool_url)
        self._lock = asyncio.Lock()

    def configure(
        self,
        proxy_url: str = "",
        proxy_pool_url: str = "",
        proxy_pool_interval: int = 60,
    ) -> None:
        self._pool_url = proxy_pool_url
        self._static_proxy = proxy_url
        self._fetch_interval = proxy_pool_interval
        self._enabled = bool(proxy_pool_url)

        if not self._enabled:
            self._current_proxy = proxy_url
            logger.info("[ProxyPool] Disabled, using static proxy: %s", proxy_url or "none")
        else:
            logger.info("[ProxyPool] Enabled with pool URL: %s", proxy_pool_url)

    @staticmethod
    def _normalize_proxy(proxy: str) -> str:
        proxy = proxy.strip()
        if not proxy:
            return ""
        if proxy.startswith("http://") or proxy.startswith("https://") or proxy.startswith("socks5h://"):
            return proxy
        if proxy.startswith("sock5/") or proxy.startswith("socks5/"):
            return "socks5h://" + proxy.split("/", 1)[1]
        return "http://" + proxy

    @staticmethod
    def _looks_like_proxy_url(url: str) -> bool:
        return any(url.startswith(p) for p in ("http://", "https://", "socks5h://"))

    async def get_proxy(self) -> Optional[str]:
        if not self._enabled:
            return self._static_proxy or None

        import time
        now = time.time()
        if now - self._last_fetch_time < self._fetch_interval:
            return self._current_proxy

        async with self._lock:
            if now - self._last_fetch_time < self._fetch_interval:
                return self._current_proxy

            proxy = await self._fetch_proxy()
            if proxy:
                self._current_proxy = proxy
                self._last_fetch_time = now
                logger.debug("[ProxyPool] Got proxy: %s", proxy)
            else:
                logger.warning("[ProxyPool] Failed to fetch proxy, using static: %s", self._static_proxy)
                self._current_proxy = self._static_proxy

        return self._current_proxy or None

    async def force_refresh(self) -> Optional[str]:
        if not self._enabled:
            return self._static_proxy or None

        async with self._lock:
            self._last_fetch_time = 0
            return await self.get_proxy()

    async def _fetch_proxy(self) -> Optional[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self._pool_url) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        return self._normalize_proxy(text)
                    logger.warning("[ProxyPool] HTTP %d from pool", resp.status)
        except Exception as e:
            logger.error("[ProxyPool] Error fetching proxy: %s", e)
        return None


proxy_pool = ProxyPool()
