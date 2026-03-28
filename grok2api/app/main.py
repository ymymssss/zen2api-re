import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.auth import auth_manager
from app.core.config import setting
from app.core.exception import (
    GrokApiException,
    grok_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.logger import logging
from app.api.v1 import chat, models, images
from app.api.admin import manage
from app.services.grok.token import token_manager
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[App] Starting grok2api...")
    await token_manager.start_batch_save()
    await auth_manager.init()
    logger.info("[App] grok2api started on port %s", setting.get("port", "8020"))
    yield
    await token_manager.shutdown()
    logger.info("[App] grok2api shutdown complete")


app = FastAPI(
    title="Grok2API - OpenAI Compatible API",
    description="OpenAI compatible API wrapper for Grok AI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(GrokApiException, grok_exception_handler)

app.include_router(chat.router, prefix="/v1", tags=["Chat"])
app.include_router(models.router, prefix="/v1", tags=["Models"])
app.include_router(images.router, prefix="/v1", tags=["Images"])
app.include_router(manage.router, prefix="", tags=["Admin"])


@app.get("/")
async def root():
    return {
        "service": "grok2api",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/v1/models")
async def list_models():
    from app.models.grok_models import GROK_MODELS

    models_list = []
    for model_id, config in GROK_MODELS.items():
        models_list.append({
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "x-ai",
            "display_name": config.get("display_name", model_id),
            "description": config.get("description", ""),
        })
    return {"object": "list", "data": models_list}


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    from app.models.grok_models import GROK_MODELS

    if model_id not in GROK_MODELS:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "invalid_request_error",
                    "message": f"Model '{model_id}' not found",
                    "code": "model_not_found",
                }
            },
        )

    config = GROK_MODELS[model_id]
    return {
        "id": model_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "x-ai",
        "display_name": config.get("display_name", model_id),
        "description": config.get("description", ""),
    }
