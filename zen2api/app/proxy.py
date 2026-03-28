"""Base proxy functionality for forwarding requests to upstream providers."""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from .adapter import normalize_model_name
from .http_client import create_async_client
from .limiters import non_modal_limiter
from .logger import get_logger
from .stats import stats
from .token_usage import (
    TokenUsage,
    extract_anthropic_sse_usage,
    parse_anthropic_usage,
)

logger = get_logger("proxy")


def _summarize_content_blocks(content: Any) -> str:
    """Summarize content blocks for logging."""
    if isinstance(content, str):
        if len(content) > 100:
            return content[:100] + "..."
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "unknown")
            if block_type == "text":
                text = block.get("text", "")
                if len(text) > 50:
                    text = text[:50] + "..."
                parts.append(f"text:{text}")
            else:
                parts.append(block_type)
        return ", ".join(parts) if parts else "empty"

    return "unknown"


async def proxy_messages(
    request: Request,
    json_body: dict[str, Any],
    is_stream: bool,
    upstream_url: str,
    headers: dict[str, str],
    last_message: str,
) -> JSONResponse | StreamingResponse:
    """Proxy Anthropic messages request to upstream."""
    model = normalize_model_name(json_body.get("model", "unknown"))

    logger.info(
        "Forward request | model=%s | stream=%s | upstream=%s | last_message=%s",
        model,
        is_stream,
        upstream_url,
        last_message,
    )

    body = json.dumps(json_body).encode("utf-8")

    if is_stream:
        return await _stream_response(model, upstream_url, headers, body)
    else:
        return await _non_stream_response(model, upstream_url, headers, body)


async def _stream_response(
    model: str,
    upstream_url: str,
    headers: dict[str, str],
    body: bytes,
) -> StreamingResponse:
    """Handle streaming response from upstream."""
    slot: str | None = None

    if non_modal_limiter:
        try:
            slot = await non_modal_limiter.acquire()
        except RuntimeError as exc:
            logger.warning("Limiter not configured | error=%s", exc)
            return StreamingResponse(
                content=f'event: error\ndata: {json.dumps({"type": "error", "error": {"type": "api_error", "message": f"rate limiter misconfigured: {exc}"}})}\n\n',
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

    start = time.monotonic()

    async def event_generator():
        nonlocal slot
        try:
            async with create_async_client() as client:
                try:
                    async with client.stream(
                        "POST",
                        upstream_url,
                        headers=headers,
                        content=body,
                    ) as resp:
                        elapsed_ms = (time.monotonic() - start) * 1000

                        if resp.status_code == 429:
                            retry_after = resp.headers.get("Retry-After", "")
                            logger.warning(
                                "Upstream stream rate limited 429 | model=%s | Retry-After=%s",
                                model,
                                retry_after,
                            )
                            yield f'event: error\ndata: {json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "rate limited by upstream"}})}\n\n'
                            return

                        if resp.status_code >= 400:
                            error_bytes = await resp.aread()
                            error_text = error_bytes.decode("utf-8", errors="ignore")
                            logger.warning(
                                "Upstream stream error | model=%s | status=%s | response=%s",
                                model,
                                resp.status_code,
                                error_text[:200],
                            )
                            yield f'event: error\ndata: {json.dumps({"type": "error", "error": {"type": "api_error", "message": f"upstream returned {error_text[:200]}"}})}\n\n'
                            return

                        logger.info(
                            "Upstream stream connected | model=%s | status=%s | elapsed=%.0fms | content_type=%s",
                            model,
                            resp.status_code,
                            elapsed_ms,
                            resp.headers.get("Content-Type", ""),
                        )

                        debug_event_count = 0
                        chunk = b""
                        async for chunk in resp.aiter_bytes():
                            chunk_text = chunk.decode("utf-8", errors="ignore")
                            yield chunk_text

                            if debug_event_count < 5:
                                lines = chunk_text.splitlines()
                                for line in lines:
                                    if line.startswith("data: "):
                                        preview = line[:200]
                                        logger.debug(
                                            "Upstream SSE sample | model=%s | event_index=%d | payload=%s",
                                            model,
                                            debug_event_count,
                                            preview,
                                        )
                                        debug_event_count += 1

                        total_ms = (time.monotonic() - start) * 1000
                        logger.info(
                            "Upstream stream completed | model=%s | total_elapsed=%.0fms",
                            model,
                            total_ms,
                        )

                        if chunk:
                            usage = extract_anthropic_sse_usage(chunk.decode("utf-8", errors="ignore"))
                            if not usage.is_empty:
                                logger.info(
                                    "Stream token usage | model=%s | input=%d | cached_input=%d | output=%d",
                                    model,
                                    usage.input_tokens,
                                    usage.cached_input_tokens,
                                    usage.output_tokens,
                                )
                                stats.record_tokens(
                                    model,
                                    usage.input_tokens,
                                    usage.output_tokens,
                                    usage.cached_input_tokens,
                                )

                except httpx.RequestError as exc:
                    logger.warning(
                        "Upstream stream connection failed | model=%s | error=%s",
                        model,
                        exc,
                    )
                    yield f'event: error\ndata: {json.dumps({"type": "error", "error": {"type": "api_error", "message": f"upstream connection failed: {exc}"}})}\n\n'

        finally:
            if slot and non_modal_limiter:
                await non_modal_limiter.release(slot)

    return StreamingResponse(
        content=event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def _non_stream_response(
    model: str,
    upstream_url: str,
    headers: dict[str, str],
    body: bytes,
) -> JSONResponse:
    """Handle non-streaming response from upstream."""
    slot: str | None = None

    if non_modal_limiter:
        try:
            slot = await non_modal_limiter.acquire()
        except RuntimeError as exc:
            logger.warning("Limiter not configured | error=%s", exc)
            return JSONResponse(
                content={
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": f"rate limiter misconfigured: {exc}",
                    },
                },
                status_code=500,
            )

    start = time.monotonic()

    try:
        async with create_async_client() as client:
            try:
                resp = await client.post(
                    upstream_url,
                    headers=headers,
                    content=body,
                )
                elapsed_ms = (time.monotonic() - start) * 1000

                logger.info(
                    "Upstream response | model=%s | status=%s | elapsed=%.0fms",
                    model,
                    resp.status_code,
                    elapsed_ms,
                )

                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After", "")
                    logger.warning(
                        "Upstream rate limited 429 | model=%s | Retry-After=%s",
                        model,
                        retry_after,
                    )
                    return JSONResponse(
                        content={
                            "type": "error",
                            "error": {
                                "type": "rate_limit_error",
                                "message": "rate limited by upstream, please retry later",
                            },
                        },
                        status_code=429,
                    )

                resp_data = resp.json()

                usage_data = resp_data.get("usage")
                if usage_data:
                    usage = parse_anthropic_usage(usage_data)
                    logger.info(
                        "Token usage | model=%s | input=%d | cached_input=%d | output=%d",
                        model,
                        usage.input_tokens,
                        usage.cached_input_tokens,
                        usage.output_tokens,
                    )
                    stats.record_tokens(
                        model,
                        usage.input_tokens,
                        usage.output_tokens,
                        usage.cached_input_tokens,
                    )

                return JSONResponse(content=resp_data, status_code=resp.status_code)

            except httpx.RequestError as exc:
                logger.warning(
                    "Upstream request failed | model=%s | error=%s",
                    model,
                    exc,
                )
                return JSONResponse(
                    content={
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": f"upstream request failed: {exc}",
                        },
                    },
                    status_code=502,
                )

    finally:
        if slot and non_modal_limiter:
            await non_modal_limiter.release(slot)
