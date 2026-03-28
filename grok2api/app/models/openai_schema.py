from typing import Dict, List, Optional, Union

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from app.models.grok_models import Models


class OpenAIChatRequest(BaseModel):
    model: str = Field(..., min_length=1, description="Model identifier")
    messages: List[Dict[str, str]] = Field(..., description="List of messages")
    stream: bool = Field(default=False, description="Enable streaming")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens to generate")
    top_p: Optional[float] = Field(default=None, description="Top-p sampling")

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: List[Union[Dict, object]]) -> list:
        if not v:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "invalid_request_error",
                        "message": "messages is required and cannot be empty",
                        "code": "invalid_request_error",
                    }
                },
            )

        msgs = []
        for msg in v:
            if isinstance(msg, dict):
                msgs.append(msg)
            else:
                msgs.append(msg.model_dump() if hasattr(msg, "model_dump") else dict(msg))

        for msg in msgs:
            if "role" not in msg:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "type": "invalid_request_error",
                            "message": "Each message must have a 'role' field",
                            "code": "invalid_request_error",
                        }
                    },
                )
            if "content" not in msg:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "type": "invalid_request_error",
                            "message": "Each message must have a 'content' field",
                            "code": "invalid_request_error",
                        }
                    },
                )
            if msg["role"] not in ("system", "user", "assistant"):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "type": "invalid_request_error",
                            "message": f"Invalid role '{msg['role']}'. Must be one of: system/user/assistant",
                            "code": "invalid_request_error",
                        }
                    },
                )

        return msgs

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if not Models.is_valid_model(v):
            supported = ", ".join(Models.get_all_model_names())
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "invalid_request_error",
                        "message": f"Model '{v}' is not supported. Supported models: {supported}",
                        "code": "model_not_found",
                    }
                },
            )
        return v


class OpenAIChatCompletionMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None
    reference_id: Optional[str] = None
    annotations: Optional[list] = None


class OpenAIChatCompletionChoice(BaseModel):
    finish_reason: Optional[str] = "stop"
    index: int = 0
    message: OpenAIChatCompletionMessage
    logprobs: Optional[object] = None


class OpenAIChatCompletionResponse(BaseModel):
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: List[OpenAIChatCompletionChoice] = []
    usage: Optional[Dict] = None


class OpenAIChatCompletionChunkMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class OpenAIChatCompletionChunkChoice(BaseModel):
    delta: OpenAIChatCompletionChunkMessage
    index: int = 0
    finish_reason: Optional[str] = None


class OpenAIChatCompletionChunkResponse(BaseModel):
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[OpenAIChatCompletionChunkChoice] = []
