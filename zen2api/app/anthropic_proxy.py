"""Anthropic format proxy to the Kilo OpenAI upstream."""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from .adapter import (
    normalize_model_name,
    stream_openai_to_anthropic,
    transform_openai_response,
    transform_request_body,
)
from .headers import build_kilo_headers
from .http_client import create_async_client
from .limiters import non_modal_limiter
from .logger import get_logger
from .stats import stats
from .token_usage import (
    TokenUsage,
    extract_anthropic_sse_usage,
    parse_openai_usage,
)

logger = get_logger("anthropic_proxy")


async def proxy_anthropic_to_kilo(
    anthropic_body: dict[str, Any],
) -> JSONResponse | StreamingResponse:
    """Convert an Anthropic request and forward it to the Kilo upstream."""
    model = normalize_model_name(anthropic_body.get("model", "unknown"))
    stream = anthropic_body.get("stream", False)
    messages = anthropic_body.get("messages", [])

    logger.info(
        "Forward Anthropic->OpenAI | model=%s | stream=%s | upstream=%s | message_count=%d",
        model,
        stream,
        config.KILO_UPSTREAM_URL,
        len(messages),
    )

    try:
        openai_body = transform_request_body(anthropic_body)
    except ValueError as exc:
        return JSONResponse(
            content={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": str(exc),
                },
            },
            status_code=400,
        )

    headers = build_kilo_headers()
    body = json.dumps(openai_body).encode("utf-8")

    if stream:
        return await _stream_response(model, headers, body)
    else:
        return await _non_stream_response(model, headers, body, anthropic_body)


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
                            yield _anthropic_error_sse(
                                "api_error",
                                f"upstream returned {error_text[:200]}",
                            )
                            return

                        content_type = resp.headers.get("Content-Type", "")
                        logger.info(
                            "Upstream stream connected | model=%s | status=%s | elapsed=%.0fms | content_type=%s",
                            model,
                            resp.status_code,
                            elapsed_ms,
                            content_type,
                        )

                        sse_text = ""
                        debug_event_count = 0
                        async for chunk in resp.aiter_bytes():
                            chunk_text = chunk.decode("utf-8", errors="ignore")
                            sse_text += chunk_text

                            if debug_event_count < 5:
                                lines = chunk_text.splitlines()
                                for line in lines:
                                    if line.startswith("data: "):
                                        preview = line[:200]
                                        logger.debug(
                                            "Converted SSE sample | model=%s | event_index=%d | payload=%s",
                                            model,
                                            debug_event_count,
                                            preview,
                                        )
                                        debug_event_count += 1

                        total_ms = (time.monotonic() - start) * 1000

                        anthropic_sse = stream_openai_to_anthropic(sse_text)
                        yield anthropic_sse

                        logger.info(
                            "Upstream stream completed | model=%s | total_elapsed=%.0fms",
                            model,
                            total_ms,
                        )

                        usage = extract_anthropic_sse_usage(anthropic_sse)
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
                    yield _anthropic_error_sse(
                        "api_error",
                        f"upstream connection failed: {exc}",
                    )

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


def _anthropic_error_sse(error_type: str, message: str) -> str:
    """Format Anthropic SSE error event."""
    return f'event: error\ndata: {json.dumps({"type": "error", "error": {"type": error_type, "message": message}})}\n\n'


def _needs_empty_text_retry(data: dict[str, Any]) -> bool:
    """Check if response needs empty text retry."""
    choices = data.get("choices", [])
    if not choices:
        return False
    first = choices[0]
    message = first.get("message", {})
    content = message.get("content", "")
    tool_calls = message.get("tool_calls")
    if isinstance(content, str) and not content.strip() and not tool_calls:
        return True
    return False


def _build_empty_text_retry_body(
    request_body: dict[str, Any],
    original_resp: dict[str, Any],
) -> dict[str, Any]:
    """Build retry body for empty text response."""
    retry_body = dict(request_body)
    messages = list(retry_body.get("messages", []))
    if messages:
        last = dict(messages[-1])
        if last.get("role") == "user":
            content = last.get("content", "")
            if isinstance(content, str):
                last["content"] = content + "\n\nPlease provide a response."
            messages[-1] = last
    retry_body["messages"] = messages

    max_tokens = retry_body.get("max_completion_tokens") or retry_body.get("max_tokens")
    if max_tokens and isinstance(max_tokens, int):
        retry_body["max_completion_tokens"] = max_tokens * 2

    return retry_body


async def _non_stream_response(
    model: str,
    headers: dict[str, str],
    body: bytes,
    request_body: dict[str, Any],
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
                            "type": "error",
                            "error": {
                                "type": "rate_limit_error",
                                "message": "rate limited by upstream",
                            },
                        },
                        status_code=429,
                    )

                if resp.status_code >= 400:
                    err_body = resp.text
                    oai_err = _extract_openai_error(err_body)
                    return JSONResponse(
                        content=oai_err,
                        status_code=resp.status_code,
                    )

                resp_data = resp.json()

                if _needs_empty_text_retry(resp_data):
                    logger.info(
                        "Empty assistant content detected; retrying with compatibility fallback | model=%s",
                        model,
                    )
                    retry_body = _build_empty_text_retry_body(
                        json.loads(body.decode("utf-8")), resp_data
                    )
                    retry_resp = await client.post(
                        config.KILO_UPSTREAM_URL,
                        headers=headers,
                        json=retry_body,
                    )
                    retry_elapsed_ms = (time.monotonic() - start) * 1000

                    logger.info(
                        "Fallback retry response | model=%s | status=%s | elapsed=%.0fms",
                        model,
                        retry_resp.status_code,
                        retry_elapsed_ms,
                    )

                    if retry_resp.status_code == 200:
                        retry_data = retry_resp.json()
                        if not _needs_empty_text_retry(retry_data):
                            anthropic_resp = transform_openai_response(retry_data)
                            return JSONResponse(content=anthropic_resp, status_code=200)
                    else:
                        logger.warning(
                            "Fallback retry request failed | model=%s | error=%s",
                            model,
                            retry_resp.text[:200],
                        )

                anthropic_resp = transform_openai_response(resp_data)

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

                return JSONResponse(content=anthropic_resp, status_code=200)

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


def _extract_openai_error(raw: str) -> dict[str, Any]:
    """Extract error from upstream response."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            error = data.get("error", {})
            raw_type = error.get("type", "api_error")
            raw_msg = error.get("message", "unknown upstream error")
            return {
                "type": "error",
                "error": {
                    "type": raw_type,
                    "message": raw_msg,
                },
            }
    except Exception:
        pass

    return {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "unknown upstream error",
        },
    }
