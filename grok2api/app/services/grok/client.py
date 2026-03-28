import asyncio
import time
from typing import Dict, List, Optional, Tuple

import aiohttp

from app.core.config import setting
from app.core.logger import logging
from app.core.proxy_pool import proxy_pool
from app.models.grok_models import Models
from app.services.grok.processer import GrokResponseProcessor
from app.services.grok.statsig import get_dynamic_headers
from app.services.grok.token import token_manager
from app.services.grok.upload import ImageUploadManager
from app.services.grok.create import PostCreateManager
from app.core.exception import GrokApiException

logger = logging.getLogger(__name__)

GROK_API_URL = "https://grok.com/rest/app-chat/conversations/new"
BROWSER = "chrome133"


class GrokClient:
    def __init__(self) -> None:
        self._upload_semr = None
        self._max_upload_concurrency = 3

    def _get_upload_semaphore(self) -> asyncio.Semaphore:
        if self._upload_semr is None:
            global_config = setting.global_config
            max_concurrency = global_config.get("max_upload_concurrency", 3)
            self._upload_semr = asyncio.Semaphore(max_concurrency)
            logger.debug("[Client] Upload semaphore initialized with max_concurrency=%d", max_concurrency)
        return self._upload_semr

    async def openai_to_grok(self, request: Dict) -> Dict:
        model = request.get("model", "grok-3-fast")
        messages = request.get("messages", [])
        stream = request.get("stream", False)

        is_video = Models.is_video_model(model)
        model_info = Models.get_model_info(model)
        grok_model = model_info.get("raw_model_path", "xai/grok-3")

        content_parts = []
        images = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                content_parts.append({"type": "system", "content": content})
            elif role == "user":
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                content_parts.append({"type": "user", "content": part.get("text", "")})
                            elif part.get("type") == "image_url":
                                images.append(part.get("image_url", {}).get("url", ""))
                else:
                    content_parts.append({"type": "user", "content": content})
            elif role == "assistant":
                content_parts.append({"type": "assistant", "content": content})

        info = {
            "model": grok_model,
            "messages": content_parts,
            "images": images,
            "is_video": is_video,
            "mode": "video" if is_video else "chat",
            "stream": stream,
        }

        return info

    async def _request(
        self,
        request_data: Dict,
        auth_token: str,
        max_retries: int = 3,
    ) -> Dict:
        if not auth_token:
            raise GrokApiException(
                message="No authentication token available",
                error_code="NO_AVAILABLE_TOKEN",
                status_code=401,
            )

        retry_status_codes = setting.grok_config.get("retry_status_codes", [403, 429, 500, 502, 503])

        for attempt in range(max_retries):
            try:
                headers = await get_dynamic_headers(auth_token, "new")
                proxy = await proxy_pool.get_proxy()

                timeout = aiohttp.ClientTimeout(total=300)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        GROK_API_URL,
                        json=request_data,
                        headers=headers,
                        proxy=proxy,
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        elif resp.status in retry_status_codes and attempt < max_retries - 1:
                            logger.warning(
                                "[Client] Token %s attempt %d failed with HTTP %d",
                                auth_token[:8],
                                attempt + 1,
                                resp.status,
                            )
                            await asyncio.sleep(1)
                            continue
                        else:
                            error_text = await resp.text()
                            raise GrokApiException(
                                message=f"HTTP {resp.status}: {error_text}",
                                error_code="REQUEST_ERROR",
                                status_code=resp.status,
                            )
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    logger.warning("[Client] Token %s attempt %d timed out", auth_token[:8], attempt + 1)
                    await asyncio.sleep(1)
                    continue
                raise GrokApiException(
                    message="Request timed out",
                    error_code="REQUEST_ERROR",
                    status_code=504,
                )
            except GrokApiException:
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning("[Client] Token %s attempt %d error: %s", auth_token[:8], attempt + 1, e)
                    await asyncio.sleep(1)
                    continue
                raise GrokApiException(
                    message=str(e),
                    error_code="REQUEST_ERROR",
                    status_code=500,
                )

        raise GrokApiException(
            message="Max retries exceeded",
            error_code="REQUEST_ERROR",
            status_code=500,
        )

    async def _upload(self, image_url: str, auth_token: str) -> Tuple[str, str]:
        semaphore = self._get_upload_semaphore()
        async with semaphore:
            uploader = ImageUploadManager()
            return await uploader.upload(image_url, auth_token)

    async def _create_post(self, file_id: str, file_uri: str, auth_token: str) -> str:
        creator = PostCreateManager()
        return await creator.create(file_id, file_uri, auth_token)

    async def chat(self, request: Dict, auth_token: str) -> Dict:
        grok_request = await self.openai_to_grok(request)
        return await self._request(grok_request, auth_token)


grok_client = GrokClient()
