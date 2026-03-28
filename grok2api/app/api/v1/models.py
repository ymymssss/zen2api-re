import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends

from app.models.grok_models import Models
from app.core.auth import auth_manager
from app.core.logger import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("")
async def list_models(auth_info: dict = Depends(auth_manager.verify)):
    try:
        model_data = []
        for model_id in Models.get_all_model_names():
            config = Models.get_model_info(model_id)
            model_data.append({
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "x-ai",
                "display_name": config.get("display_name", model_id),
                "description": config.get("description", ""),
                "raw_model_path": config.get("raw_model_path", ""),
                "default_temperature": config.get("default_temperature", 0.7),
                "default_max_output_tokens": config.get("default_max_output_tokens", 4096),
                "supported_max_output_tokens": config.get("supported_max_output_tokens", 16384),
                "default_top_p": config.get("default_top_p", 0.95),
            })

        return {"object": "list", "data": model_data}

    except Exception as e:
        logger.error("[Models] Failed to retrieve models: %s", str(e))
        return HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "internal_error",
                    "message": "Failed to retrieve models",
                    "code": "model_list_error",
                }
            },
        )


@router.get("/{model_id}")
async def get_model(
    model_id: str,
    auth_info: dict = Depends(auth_manager.verify),
):
    try:
        if not Models.is_valid_model(model_id):
            return HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "type": "invalid_request_error",
                        "message": f"Model '{model_id}' not found",
                        "code": "model_not_found",
                    }
                },
            )

        config = Models.get_model_info(model_id)
        return {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "x-ai",
            "display_name": config.get("display_name", model_id),
            "description": config.get("description", ""),
            "raw_model_path": config.get("raw_model_path", ""),
            "default_temperature": config.get("default_temperature", 0.7),
            "default_max_output_tokens": config.get("default_max_output_tokens", 4096),
            "supported_max_output_tokens": config.get("supported_max_output_tokens", 16384),
            "default_top_p": config.get("default_top_p", 0.95),
        }

    except Exception as e:
        logger.error("[Models] Failed to retrieve model: %s", str(e))
        return HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "internal_error",
                    "message": "Failed to retrieve model",
                    "code": "model_retrieve_error",
                }
            },
        )
