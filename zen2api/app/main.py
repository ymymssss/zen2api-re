"""FastAPI application entry point for zen2api."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from . import config
from .build_info import format_build_label, get_runtime_build_info
from .logger import setup as setup_logging, should_log_request
from .model_registry import get_model_catalog, warm_model_catalog
from .openai_zen_proxy import proxy_openai_to_zen
from .kilo_proxy import proxy_chat_completions, proxy_chat_completions_json
from .responses_adapter import (
    stream_chat_to_responses,
    transform_chat_response_to_responses,
    transform_responses_request_to_chat,
)
from .startup_banner import build_zen2api_panel, log_panel, resolve_panel_style
from .stats import stats
from .license_guard import enforce_runtime_license, is_frozen_runtime

app = FastAPI(
    title="zen2api",
    version=__version__,
    summary="OpenAI/Anthropic/Kilo proxy with model discovery",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_stats_log_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    global _stats_log_task

    setup_logging()
    enforce_runtime_license()

    build_label = format_build_label(__version__)
    style = resolve_panel_style()
    panel = build_zen2api_panel(
        host=config.HOST,
        port=config.PORT,
        auth_enabled=config.auth_enabled,
        build_label=build_label,
        model_discovery_enabled=config.MODEL_DISCOVERY_ENABLED,
        model_discovery_ttl_seconds=config.MODEL_DISCOVERY_TTL_SECONDS,
        zen_models=config.ZEN_MODELS,
        kilo_models=config.KILO_MODELS,
        non_modal_rps=config.NON_MODAL_RPS,
        stats_file=config.STATS_FILE,
        stats_log_interval=config.STATS_LOG_INTERVAL,
        version=__version__,
        style=style,
    )
    log_panel(panel)

    asyncio.create_task(warm_model_catalog())

    async def _stats_log_task():
        while True:
            await asyncio.sleep(config.STATS_LOG_INTERVAL)
            from .logger import get_logger
            logger = get_logger("stats")
            logger.info(stats.summary())

    _stats_log_task = asyncio.create_task(_stats_log_task())


@app.on_event("shutdown")
async def shutdown():
    global _stats_log_task
    if _stats_log_task:
        _stats_log_task.cancel()


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method

    if not should_log_request_simple(path):
        return await call_next(request)

    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000

    from .logger import get_logger
    logger = get_logger("http")
    logger.info(
        "%s %s -> %s (%.0fms)",
        method,
        path,
        response.status_code,
        elapsed_ms,
    )

    return response


def should_log_request_simple(path: str) -> bool:
    if path == "/health" and not config.LOG_HEALTH_CHECK:
        return False
    if path.upper() == "OPTIONS":
        return False
    return True


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not config.auth_enabled:
        return await call_next(request)

    path = request.url.path

    if path in ("/health", "/stats", "/stats/report", "/stats/reset"):
        return await call_next(request)

    if path.startswith("/v1/models"):
        return await call_next(request)

    api_key = request.headers.get("x-api-key", "")
    auth_header = request.headers.get("authorization", "")

    if auth_header.lower().startswith("bearer "):
        api_key = auth_header[7:]

    if not api_key or api_key.strip() != config.API_KEY:
        from .logger import get_logger
        logger = get_logger("auth")
        source = "x-api-key" if request.headers.get("x-api-key") else "authorization"
        logger.warning(
            "Auth failed | path=%s | source=%s",
            path,
            source,
        )
        return JSONResponse(
            content={
                "error": {
                    "type": "authentication_error",
                    "message": "invalid api key",
                }
            },
            status_code=401,
        )

    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/stats")
async def get_stats():
    return stats.get_stats()


@app.get("/stats/report")
async def report_stats():
    return stats.summary()


@app.post("/stats/reset")
async def reset_stats():
    stats.reset()
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    catalog = await get_model_catalog()

    anthropic_version = config.ZEN_ANTHROPIC_VERSION
    display_name_map = {}

    data = []
    for model_id in catalog.all_models:
        data.append({
            "id": model_id,
            "display_name": display_name_map.get(model_id, model_id),
            "created_at": "2025-01-01T00:00:00Z",
            "object": "model",
            "owned_by": "zen2api",
        })

    return {
        "data": data,
        "has_more": False,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
        "object": "list",
    }


@app.post("/v1/messages")
async def messages(request: Request):
    try:
        json_body = await request.json()
    except Exception:
        return JSONResponse(
            content={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "invalid JSON body",
                },
            },
            status_code=400,
        )

    model = json_body.get("model", "unknown")
    stream = json_body.get("stream", False)

    from .logger import get_logger
    logger = get_logger("api")
    messages_list = json_body.get("messages", [])
    logger.info(
        "Incoming /v1/messages | model=%s | stream=%s | route=%s | message_count=%d",
        model,
        stream,
        "kilo",
        len(messages_list),
    )

    catalog = await get_model_catalog()
    route = catalog.route_for(model)

    if route == "kilo":
        from .anthropic_proxy import proxy_anthropic_to_kilo
        return await proxy_anthropic_to_kilo(json_body)
    else:
        from .proxy import proxy_messages
        return await proxy_messages(
            request,
            json_body,
            stream,
            config.ZEN_UPSTREAM_URL,
            {},
            _summarize_last_message(messages_list),
        )


def _summarize_last_message(messages: list) -> str:
    if not messages:
        return ""
    last = messages[-1]
    content = last.get("content", "")
    if isinstance(content, str):
        return content[:100]
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", "")[:50])
        return " | ".join(parts)
    return ""


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        json_body = await request.json()
    except Exception:
        return JSONResponse(
            content={
                "error": {
                    "message": "invalid JSON body",
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    return await proxy_openai_to_zen(json_body)


@app.post("/v1/responses")
async def responses(request: Request):
    try:
        json_body = await request.json()
    except Exception:
        return JSONResponse(
            content={
                "error": {
                    "message": "invalid JSON body",
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    try:
        chat_body = transform_responses_request_to_chat(json_body)
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

    stream = json_body.get("stream", False)

    if stream:
        chat_body["stream"] = True
        openai_resp = await proxy_openai_to_zen(chat_body)

        if isinstance(openai_resp, StreamingResponse):
            return StreamingResponse(
                content=stream_chat_to_responses(openai_resp.body_iterator),
                media_type="text/event-stream",
            )
        return openai_resp
    else:
        openai_resp = await proxy_openai_to_zen(chat_body)

        if isinstance(openai_resp, JSONResponse):
            resp_data = openai_resp.body
            if isinstance(resp_data, bytes):
                import json as json_module
                resp_objs = json_module.loads(resp_data)
            else:
                resp_objs = resp_data

            responses_body = transform_chat_response_to_responses(
                resp_objs, json_body
            )
            return JSONResponse(
                content=responses_body,
                status_code=openai_resp.status_code,
            )

        return openai_resp


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
    )
