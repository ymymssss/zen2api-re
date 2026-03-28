import asyncio
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.auth import auth_manager
from app.core.exception import GrokApiException
from app.core.logger import logging
from app.services.grok.client import GrokClient
from app.models.openai_schema import OpenAIChatRequest
from app.services.request_stats import request_stats
from app.services.request_logger import request_logger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


async def stream_wrapper(response_iterator, start_time, key_name, model):
    try:
        async for chunk in response_iterator:
            yield chunk
    except Exception as e:
        logger.error("[Chat] Stream error: %s", str(e))
        raise
    finally:
        duration = time.time() - start_time
        request_stats.record_request(
            key_name=key_name,
            model=model,
            duration=duration,
            success=True,
            streaming=True,
        )
        request_logger.add_log(
            key_name=key_name,
            model=model,
            duration=duration,
            result="success",
            streaming=True,
        )


@router.post("/completions", response_model=None)
async def chat_completions(
    request: Request,
    body: OpenAIChatRequest,
    auth_info: dict = Depends(auth_manager.verify),
):
    start_time = time.time()
    key_name = auth_info.get("name", "unknown")
    model = body.model

    try:
        client = GrokClient()
        grok_config = auth_info.get("grok_config", {})

        auth_token = grok_config.get("api_key", "")
        if not auth_token:
            raise GrokApiException(
                message="No authentication token available",
                error_code="NO_AVAILABLE_TOKEN",
                status_code=401,
            )

        request_data = await client.openai_to_grok(body.model_dump())

        if body.stream:
            response_iterator = await client.stream_chat(request_data, auth_token)

            return StreamingResponse(
                stream_wrapper(response_iterator, start_time, key_name, model),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            result = await client.chat(request_data, auth_token)

            duration = time.time() - start_time
            request_stats.record_request(
                key_name=key_name,
                model=model,
                duration=duration,
                success=True,
                streaming=False,
            )
            request_logger.add_log(
                key_name=key_name,
                model=model,
                duration=duration,
                result="success",
                streaming=False,
            )

            return result

    except GrokApiException as e:
        duration = time.time() - start_time
        request_stats.record_request(
            key_name=key_name,
            model=model,
            duration=duration,
            success=False,
            streaming=False,
        )
        request_logger.add_log(
            key_name=key_name,
            model=model,
            duration=duration,
            result="error",
            error_msg=str(e),
            streaming=False,
        )

        return HTTPException(
            status_code=e.status_code,
            detail={
                "error": {
                    "type": "grok_api_error",
                    "message": str(e),
                    "code": e.error_code,
                }
            },
        )

    except Exception as e:
        duration = time.time() - start_time
        request_stats.record_request(
            key_name=key_name,
            model=model,
            duration=duration,
            success=False,
            streaming=False,
        )
        request_logger.add_log(
            key_name=key_name,
            model=model,
            duration=duration,
            result="error",
            error_msg=str(e),
            streaming=False,
        )

        return HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "internal_error",
                    "message": "Internal server error",
                    "code": "internal_server_error",
                }
            },
        )
