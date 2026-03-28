"""Grok response processor with streaming support."""
from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, Tuple

from ...core.config import setting
from ...core.exception import GrokApiException
from ...core.logger import logger
from ...models.openai_schema import (
    OpenAIChatCompletionResponse,
    OpenAIChatCompletionChoice,
    OpenAIChatCompletionMessage,
    OpenAIChatCompletionChunkResponse,
    OpenAIChatCompletionChunkChoice,
    OpenAIChatCompletionChunkMessage,
)


class StreamTimeoutManager:
    """Manages streaming timeouts."""

    def __init__(
        self,
        chunk_timeout: int = 30,
        first_timeout: int = 60,
        total_timeout: int = 300,
    ):
        self.chunk_timeout = chunk_timeout
        self.first_timeout = first_timeout
        self.total_timeout = total_timeout
        self._loop = None
        self.start_time = 0.0
        self.last_chunk_time = 0.0
        self.first_received = False

    def check_timeout(self) -> bool:
        """Check if timeout has been exceeded."""
        now = time.time()
        if not self.first_received:
            return (now - self.start_time) > self.first_timeout
        return (now - self.last_chunk_time) > self.chunk_timeout

    def mark_received(self):
        """Mark that a chunk was received."""
        self.last_chunk_time = time.time()
        if not self.first_received:
            self.first_received = True

    def duration(self) -> float:
        """Get elapsed time."""
        return time.time() - self.start_time


class GrokResponseProcessor:
    """Processes Grok API responses into OpenAI format."""

    def __init__(self, auth_token: str, model: str):
        self.auth_token = auth_token
        self.model = model

    async def process_response(self, response: dict) -> OpenAIChatCompletionResponse:
        """Process a Grok response into OpenAI format."""
        if "error" in response:
            raise GrokApiException(
                message=response.get("error", {}).get("message", "API error"),
                code=response.get("error", {}).get("code", "API_ERROR"),
            )

        result = response.get("result", response)

        if "streamingVideoGenerationResponse" in result:
            video_url = result.get("streamingVideoGenerationResponse", {}).get("videoUrl")
            return self._build_response(f"[Video: {video_url}]")

        model_response = result.get("modelResponse", {})
        if not model_response:
            raise GrokApiException(
                message="No response from model",
                code="NO_RESPONSE",
            )

        generated_image_urls = model_response.get("generatedImageUrls", [])
        if generated_image_urls:
            image_text = "\n".join(f"[Image: {url}]" for url in generated_image_urls)
            return self._build_response(image_text)

        message = model_response.get("message", "")
        return self._build_response(message)

    async def process_stream(
        self, stream: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[str, None]:
        """Process a streaming response."""
        timeout_mgr = StreamTimeoutManager()
        timeout_mgr.start_time = time.time()

        try:
            async for chunk in stream:
                if timeout_mgr.check_timeout():
                    logger.warning("[Processor] Stream timeout")
                    break

                timeout_mgr.mark_received()
                yield chunk.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"[Processor] Stream error: {e}")
            raise GrokApiException(
                message=f"Stream processing error: {e}",
                code="PROCESS_ERROR",
            )

    def _build_response(self, message: str) -> OpenAIChatCompletionResponse:
        """Build OpenAI-compatible response."""
        return OpenAIChatCompletionResponse(
            id=f"grok-{int(time.time())}",
            object="chat.completion",
            created=int(time.time()),
            model=self.model,
            choices=[
                OpenAIChatCompletionChoice(
                    index=0,
                    message=OpenAIChatCompletionMessage(
                        role="assistant",
                        content=message,
                    ),
                    finish_reason="stop",
                )
            ],
        )


# Cache services (lazy loaded)
image_cache_service = None
video_cache_service = None
