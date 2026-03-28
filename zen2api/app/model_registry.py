"""Dynamic free-model discovery and routing helpers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from . import config
from .http_client import create_async_client
from .headers import build_kilo_headers, build_zen_headers
from .logger import get_logger

logger = get_logger("model_registry")


@dataclass(frozen=True)
class ModelCatalog:
    zen_models: tuple[str, ...]
    kilo_models: tuple[str, ...]
    zen_source: str
    kilo_source: str
    refreshed_at: float

    @property
    def all_models(self) -> tuple[str, ...]:
        return self.zen_models + self.kilo_models

    def is_probably_kilo_model(self, model: str) -> bool:
        return model in self.kilo_models

    def route_for(self, model: str) -> str:
        if model in self.kilo_models:
            return "kilo"
        return "zen"


_cache: Optional[ModelCatalog] = None
_cache_expires_at: float = 0.0
_lock: asyncio.Lock = asyncio.Lock()


def _dedupe_models(
    discovered: list[str],
    manual_overrides: list[str],
    fallback: list[str],
) -> tuple[str, ...]:
    """Deduplicate and order models."""
    seen: set[str] = set()
    ordered: list[str] = []

    for raw in [manual_overrides, discovered, fallback]:
        for model in raw:
            model = model.strip()
            if not model:
                continue
            if model not in seen:
                seen.add(model)
                ordered.append(model)

    return tuple(ordered)


def _merge_models(
    discovered: list[str],
    manual_overrides: list[str],
    fallback: list[str],
) -> tuple[str, ...]:
    return _dedupe_models(discovered, manual_overrides, fallback)


def _select_kilo_free_model_ids(payload: dict) -> list[str]:
    """Select free model IDs from Kilo response."""
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []

    free_ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id", "")
        pricing = item.get("pricing", {})
        if isinstance(pricing, dict):
            prompt = pricing.get("prompt", "0")
            completion = pricing.get("completion", "0")
            if prompt == "0" and completion == "0" and model_id:
                free_ids.append(model_id)

    return free_ids


def _select_zen_candidate_model_ids(payload: dict) -> list[str]:
    """Select candidate model IDs from Zen response."""
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []

    candidate_ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id", "")
        if model_id and model_id.lower().endswith("-free"):
            candidate_ids.append(model_id)

    return candidate_ids


def _fallback_catalog() -> ModelCatalog:
    """Create fallback catalog from config."""
    now = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0.0
    return ModelCatalog(
        zen_models=tuple(config.ZEN_MODELS),
        kilo_models=tuple(config.KILO_MODELS),
        zen_source="config",
        kilo_source="config",
        refreshed_at=now,
    )


async def get_model_catalog(force_refresh: bool = False) -> ModelCatalog:
    """Get model catalog, refreshing if needed."""
    global _cache, _cache_expires_at

    if not config.MODEL_DISCOVERY_ENABLED:
        return _fallback_catalog()

    import time
    now = time.monotonic()

    if not force_refresh and _cache and now < _cache_expires_at:
        return _cache

    async with _lock:
        if not force_refresh and _cache and now < _cache_expires_at:
            return _cache

        try:
            catalog = await _refresh_catalog()
            _cache = catalog
            _cache_expires_at = now + config.MODEL_DISCOVERY_TTL_SECONDS
            return catalog
        except Exception:
            if _cache:
                return _cache
            return _fallback_catalog()


async def warm_model_catalog() -> None:
    """Warm the model catalog cache on startup."""
    try:
        catalog = await get_model_catalog(force_refresh=True)
        logger.info(
            "Model catalog refreshed | zen=%d (%s) | kilo=%d (%s)",
            len(catalog.zen_models),
            catalog.zen_source,
            len(catalog.kilo_models),
            catalog.kilo_source,
        )
    except Exception as exc:
        logger.warning("Model discovery transport failed | error=%s", exc)


async def _refresh_catalog() -> ModelCatalog:
    """Refresh catalog from upstream."""
    import time

    timeout = httpx.Timeout(config.MODEL_DISCOVERY_TIMEOUT_SECONDS)

    async with create_async_client(timeout=timeout) as client:
        zen_result, kilo_result = await asyncio.gather(
            _discover_zen_models(client),
            _discover_kilo_models(client),
            return_exceptions=True,
        )

    zen_models: list[str] = []
    zen_source = "config"
    kilo_models: list[str] = []
    kilo_source = "config"

    if isinstance(zen_result, Exception):
        logger.warning("Zen model discovery failed | error=%s", zen_result)
    elif zen_result:
        zen_models = zen_result
        zen_source = "discovered"

    if isinstance(kilo_result, Exception):
        logger.warning("Kilo model discovery failed | error=%s", kilo_result)
    elif kilo_result:
        kilo_models = kilo_result
        kilo_source = "discovered"

    return ModelCatalog(
        zen_models=_merge_models(zen_models, list(config.ZEN_MODELS), list(config.DEFAULT_ZEN_FALLBACK_MODELS)),
        kilo_models=_merge_models(kilo_models, list(config.KILO_MODELS), list(config.DEFAULT_KILO_FALLBACK_MODELS)),
        zen_source=zen_source,
        kilo_source=kilo_source,
        refreshed_at=time.monotonic(),
    )


async def _discover_zen_models(client: httpx.AsyncClient) -> list[str]:
    """Discover available Zen models."""
    headers = build_zen_headers()

    response = await client.get(config.ZEN_MODELS_URL, headers=headers)
    response.raise_for_status()

    payload = response.json()
    candidate_ids = _select_zen_candidate_model_ids(payload)

    live_ids: list[str] = []
    for model_id in candidate_ids:
        if await _probe_zen_model(client, model_id):
            live_ids.append(model_id)

    return live_ids


async def _discover_kilo_models(client: httpx.AsyncClient) -> list[str]:
    """Discover available Kilo free models."""
    headers = build_kilo_headers()

    response = await client.get(config.KILO_MODELS_URL, headers=headers)
    response.raise_for_status()

    payload = response.json()
    candidate_ids = _select_kilo_free_model_ids(payload)

    live_ids: list[str] = []
    for model_id in candidate_ids:
        if await _probe_kilo_model(client, model_id):
            live_ids.append(model_id)

    return live_ids


async def _probe_zen_model(client: httpx.AsyncClient, model: str) -> bool:
    """Probe if a Zen model is available."""
    headers = build_zen_headers()
    body = {
        "model": model,
        "max_tokens": 1,
        "stream": False,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
    }

    try:
        response = await client.post(
            config.ZEN_UPSTREAM_URL,
            headers=headers,
            json=body,
        )
        if response.status_code == 200:
            return True
        preview = response.text[:200] if response.text else ""
        logger.warning(
            "Zen model probe rejected | model=%s | status=%s | body=%s",
            model,
            response.status_code,
            preview,
        )
        return False
    except Exception as exc:
        logger.warning("Zen model probe failed | model=%s | error=%s", model, exc)
        return False


async def _probe_kilo_model(client: httpx.AsyncClient, model: str) -> bool:
    """Probe if a Kilo model is available."""
    headers = build_kilo_headers()
    body = {
        "model": model,
        "max_tokens": 1,
        "stream": False,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
    }

    try:
        response = await client.post(
            config.KILO_UPSTREAM_URL,
            headers=headers,
            json=body,
        )
        if response.status_code == 200:
            return True
        preview = response.text[:200] if response.text else ""
        logger.warning(
            "Kilo model probe rejected | model=%s | status=%s | body=%s",
            model,
            response.status_code,
            preview,
        )
        return False
    except Exception as exc:
        logger.warning("Kilo model probe failed | model=%s | error=%s", model, exc)
        return False


import httpx
