"""Shared httpx client factory with stable runtime defaults."""
from __future__ import annotations

import httpx


def create_async_client(
    timeout: httpx.Timeout | None = None,
    trust_env: bool = False,
) -> httpx.AsyncClient:
    """Create an async HTTP client with default settings."""
    if timeout is None:
        timeout = httpx.Timeout(30.0, connect=10.0)

    return httpx.AsyncClient(
        timeout=timeout,
        trust_env=trust_env,
    )
