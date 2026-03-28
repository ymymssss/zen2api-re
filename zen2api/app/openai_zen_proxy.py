"""OpenAI chat/completions format proxy to the Zen Anthropic upstream."""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from .adapter import (
    normalize_model_name,
    stream_anthropic_to_openai,
    transform_openai_response,
    transform_request_body,
)
from .headers import build_zen_headers
from .http_client import create_async_client
from .limiters import non_modal_limiter
from .logger import get_logger
from .stats import stats
from .token_usage import (
    TokenUsage,
    extract_openai_sse_usage,
    parse_anthropic_usage,
)

logger = get_logger("openai_zen_proxy")


async def proxy_openai_to_zen(
    openai_body: dict[str, Any],
) -> JSONResponse | StreamingResponse:
    """Convert an OpenAI chat request and forward it to the Zen upstream."""
    model = normalize_model_name(openai_body.get("model", "unknown"))

    error = openai_body.get("error")
    if error:
        return JSONResponse(
            content={
                "error": {
                    "message": error.get("message", "unknown error"),
                    "type": error.get("type", "invalid_request_error"),
                }
            },
            status_code=error.get("status_code", 400),
        )

    stream = openai_body.get("stream", False)

    try:
        anthropic_body = transform_request_body(openai_body)
    except ValueError as exc:
        return JSONResponse(
            content={
                "error": {
                    "message": str(exc),
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    logger.info(
        "Forward OpenAI->Anthropic | model=%s | stream=%s | upstream=%s",
        model,
        stream,
        config.ZEN_UPSTREAM_URL,
    )

    headers = build_zen_headers()
    body = json.dumps(anthropic_body).encode("utf-8")

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
            logger.warning("Limiter not configured | error=%s", exc)
            return StreamingResponse(
                content=f'data: {json.dumps({"error": {"type": "api_error", "message": f"rate limiter misconfigured: {exc}"}})}\n\ndata: [DONE]\n\n',
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
                        config.ZEN_UPSTREAM_URL,
                        headers=headers,
                        content=body,
                    ) as resp:
                        elapsed_ms = (time.monotonic() - start) * 1000

                        if resp.status_code == 429:
                            logger.warning(
                                "Upstream stream rate limited 429 | model=%s",
                                model,
                            )
                            yield f'data: {json.dumps({"error": {"type": "rate_limit_error", "message": "rate limited by upstream"}})}\n\ndata: [DONE]\n\n'
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
                            yield f'data: {json.dumps({"error": {"type": "api_error", "message": f"upstream returned {error_text[:200]}"}})}\n\ndata: [DONE]\n\n'
                            return

                        logger.info(
                            "Upstream stream connected | model=%s | status=%s | elapsed=%.0fms",
                            model,
                            resp.status_code,
                            elapsed_ms,
                        )

                        sse_text = ""
                        total_ms = 0.0
                        async for chunk in resp.aiter_bytes():
                            chunk_text = chunk.decode("utf-8", errors="ignore")
                            sse_text += chunk_text

                        total_ms = (time.monotonic() - start) * 1000

                        openai_sse = stream_anthropic_to_openai(sse_text)
                        yield openai_sse

                        logger.info(
                            "Upstream stream completed | model=%s | total_elapsed=%.0fms",
                            model,
                            total_ms,
                        )

                        usage = extract_openai_sse_usage(openai_sse)
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
                    yield f'data: {json.dumps({"error": {"type": "api_error", "message": f"upstream connection failed: {exc}"}})}\n\ndata: [DONE]\n\n'

        finally:
            if slot and non_modal_limiter:
                await non_modal_limiter.release(slot)

    return StreamingResponse(
        content=event_generator(),
        media_type="text/event-stream",
    )


def _decode_json(raw: bytes) -> dict[str, Any] | None:
    """Decode JSON from bytes."""
    try:
        return json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception:
        return None


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
            logger.warning("Limiter not configured | error=%s", exc)
            return JSONResponse(
                content={
                    "error": {
                        "type": "api_error",
                        "message": f"rate limiter misconfigured: {exc}",
                    }
                },
                status_code=500,
            )

    start = time.monotonic()

    try:
        async with create_async_client() as client:
            try:
                resp = await client.post(
                    config.ZEN_UPSTREAM_URL,
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
                                "type": "rate_limit_error",
                                "message": "rate limited by upstream",
                            }
                        },
                        status_code=429,
                    )

                if resp.status_code >= 400:
                    err_body = resp.text
                    err_data = _extract_openai_error(err_body)
                    return JSONResponse(
                        content=err_data,
                        status_code=resp.status_code,
                    )

                resp_data = resp.json()
                openai_resp = transform_openai_response(resp_data)

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

                return JSONResponse(content=openai_resp, status_code=200)

            except httpx.RequestError as exc:
                logger.warning(
                    "Upstream request failed | model=%s | error=%s",
                    model,
                    exc,
                )
                return JSONResponse(
                    content={
                        "error": {
                            "type": "api_error",
                            "message": f"upstream request failed: {exc}",
                        }
                    },
                    status_code=502,
                )

    finally:
        if slot and non_modal_limiter:
            await non_modal_limiter.release(slot)


def _extract_openai_error(raw: str) -> dict[str, Any]:
    """Extract error from upstream response."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "error" in data:
            return data
    except Exception:
        pass

    return {
        "error": {
            "type": "api_error",
            "message": "unknown upstream error",
        }
    }
