"""Kilo proxy for forwarding OpenAI requests to Kilo upstream."""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from .adapter import normalize_model_name
from .headers import build_kilo_headers
from .http_client import create_async_client
from .limiters import non_modal_limiter
from .logger import get_logger
from .stats import stats
from .token_usage import (
    TokenUsage,
    extract_openai_sse_usage,
    parse_openai_usage,
)

logger = get_logger("kilo_proxy")


async def proxy_chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """Proxy OpenAI chat/completions request to Kilo upstream."""
    try:
        json_body = await request.json()
    except Exception:
        logger.warning("Failed to parse request JSON body")
        return JSONResponse(
            content={
                "error": {
                    "message": "invalid JSON body",
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    return await _proxy_chat_completions(json_body)


async def proxy_chat_completions_json(
    body: bytes,
) -> JSONResponse | StreamingResponse:
    """Proxy OpenAI chat/completions JSON to Kilo upstream."""
    try:
        json_body = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse(
            content={
                "error": {
                    "message": "invalid JSON",
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    return await _proxy_chat_completions(json_body)


async def _proxy_chat_completions(
    json_body: dict[str, Any],
) -> JSONResponse | StreamingResponse:
    """Internal proxy for chat completions."""
    model = normalize_model_name(json_body.get("model", "unknown"))
    stream = json_body.get("stream", False)

    logger.info(
        "Forward request | model=%s | stream=%s | upstream=%s",
        model,
        stream,
        config.KILO_UPSTREAM_URL,
    )

    headers = build_kilo_headers()
    body = json.dumps(json_body).encode("utf-8")

    if stream:
        return await _stream_response(model, headers, body)
    else:
        return await _non_stream_response(model, headers, body)


async def _stream_response(
    model: str,
    headers: dict[str, str],
    body: bytes,
) -> StreamingResponse:
    """Handle streaming response."""
    slot: str | None = None

    if non_modal_limiter:
        try:
            slot = await non_modal_limiter.acquire()
        except RuntimeError as exc:
            logger.warning("Non-modal limiter not configured | error=%s", exc)
            return StreamingResponse(
                content=f'data: {json.dumps({"error": {"message": f"rate limiter misconfigured: {exc}", "type": "api_error"}})}\n\ndata: [DONE]\n\n',
                media_type="text/event-stream",
            )

    start = time.monotonic()

    async def event_generator():
        nonlocal slot
        try:
            async with create_async_client() as client:
                try:
                    async with client.stream(
                        "POST",
                        config.KILO_UPSTREAM_URL,
                        headers=headers,
                        content=body,
                    ) as resp:
                        elapsed_ms = (time.monotonic() - start) * 1000

                        if resp.status_code == 429:
                            logger.warning(
                                "Upstream stream rate limited 429 | model=%s",
                                model,
                            )
                            yield f'data: {json.dumps({"error": {"message": "rate limited by upstream", "type": "rate_limit_error"}})}\n\ndata: [DONE]\n\n'
                            return

                        if resp.status_code >= 400:
                            error_bytes = await resp.aread()
                            error_text = error_bytes.decode("utf-8", errors="replace")
                            logger.warning(
                                "Upstream stream error | model=%s | status=%s | response=%s",
                                model,
                                resp.status_code,
                                error_text[:200],
                            )
                            yield f'data: {json.dumps({"error": {"message": f"upstream returned {error_text[:200]}", "type": "api_error"}})}\n\ndata: [DONE]\n\n'
                            return

                        logger.info(
                            "Upstream stream connected | model=%s | status=%s | elapsed=%.0fms",
                            model,
                            resp.status_code,
                            elapsed_ms,
                        )

                        total_ms = 0.0
                        async for chunk in resp.aiter_bytes():
                            chunk_text = chunk.decode("utf-8", errors="ignore")
                            yield chunk_text

                        total_ms = (time.monotonic() - start) * 1000
                        logger.info(
                            "Upstream stream completed | model=%s | total_elapsed=%.0fms",
                            model,
                            total_ms,
                        )

                except httpx.RequestError as exc:
                    logger.warning(
                        "Upstream stream connection failed | model=%s | error=%s",
                        model,
                        exc,
                    )
                    yield f'data: {json.dumps({"error": {"message": f"upstream connection failed: {exc}", "type": "api_error"}})}\n\ndata: [DONE]\n\n'

        finally:
            if slot and non_modal_limiter:
                await non_modal_limiter.release(slot)

    return StreamingResponse(
        content=event_generator(),
        media_type="text/event-stream",
    )


async def _non_stream_response(
    model: str,
    headers: dict[str, str],
    body: bytes,
) -> JSONResponse:
    """Handle non-streaming response."""
    slot: str | None = None

    if non_modal_limiter:
        try:
            slot = await non_modal_limiter.acquire()
        except RuntimeError as exc:
            logger.warning("Non-modal limiter not configured | error=%s", exc)
            return JSONResponse(
                content={
                    "error": {
                        "message": f"rate limiter misconfigured: {exc}",
                        "type": "api_error",
                    }
                },
                status_code=500,
            )

    start = time.monotonic()

    try:
        async with create_async_client() as client:
            try:
                resp = await client.post(
                    config.KILO_UPSTREAM_URL,
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
                    logger.warning(
                        "Upstream rate limited 429 | model=%s",
                        model,
                    )
                    return JSONResponse(
                        content={
                            "error": {
                                "message": "rate limited by upstream",
                                "type": "rate_limit_error",
                            }
                        },
                        status_code=429,
                    )

                if resp.status_code >= 400:
                    err_body = resp.text
                    return JSONResponse(
                        content={
                            "error": {
                                "message": f"upstream returned non-JSON response (status {resp.status_code})",
                                "type": "api_error",
                            }
                        },
                        status_code=resp.status_code,
                    )

                resp_data = resp.json()

                usage_data = resp_data.get("usage")
                if usage_data:
                    usage = parse_openai_usage(usage_data)
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

                return JSONResponse(content=resp_data, status_code=200)

            except httpx.RequestError as exc:
                logger.warning(
                    "Upstream request failed | model=%s | error=%s",
                    model,
                    exc,
                )
                return JSONResponse(
                    content={
                        "error": {
                            "message": f"upstream request failed: {exc}",
                            "type": "api_error",
                        }
                    },
                    status_code=502,
                )

    finally:
        if slot and non_modal_limiter:
            await non_modal_limiter.release(slot)
