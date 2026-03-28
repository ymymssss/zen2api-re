import asyncio
from typing import Dict, Optional

import aiohttp

from app.core.config import setting
from app.core.exception import GrokApiException
from app.core.logger import logging
from app.core.proxy_pool import proxy_pool
from app.services.grok.statsig import get_dynamic_headers

logger = logging.getLogger(__name__)

CREATE_POST_URL = "https://grok.com/rest/media/post/create"
BROWSER = "chrome133"


class PostCreateManager:
    async def create(
        self,
        file_id: str,
        file_uri: str,
        auth_token: str,
    ) -> str:
        if not file_id or not file_uri:
            raise GrokApiException(
                message="file_id and file_uri are required",
                error_code="INVALID_PARAMS",
                status_code=400,
            )

        if not auth_token:
            raise GrokApiException(
                message="No authentication token available",
                error_code="NO_AUTH_TOKEN",
                status_code=401,
            )

        media_url = f"https://assets.grok.com/{file_uri}"
        media_type = "MEDIA_POST_TYPE_IMAGE"

        grok_config = setting.grok_config
        cf_clearance = grok_config.get("cf_clearance", "")

        headers = {
            "Cookie": f"cf_clearance={cf_clearance}",
            "Content-Type": "application/json",
        }

        data = {
            "mediaUrl": media_url,
            "mediaType": media_type,
        }

        retry_status_codes = setting.grok_config.get("retry_status_codes", [403, 429, 500, 502, 503])

        for attempt in range(3):
            try:
                proxy = await proxy_pool.get_proxy()
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        CREATE_POST_URL,
                        json=data,
                        headers=headers,
                        proxy=proxy,
                    ) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            post_id = result.get("post", {}).get("postId")
                            if post_id:
                                logger.debug("[PostCreate] Created post ID: %s", post_id)
                                return post_id
                            else:
                                raise GrokApiException(
                                    message="No post ID in response",
                                    error_code="CREATE_ERROR",
                                    status_code=500,
                                )
                        elif resp.status in retry_status_codes and attempt < 2:
                            logger.warning("[PostCreate] Attempt %d failed with HTTP %d", attempt + 1, resp.status)
                            await asyncio.sleep(1)
                            continue
                        else:
                            error_text = await resp.text()
                            raise GrokApiException(
                                message=f"HTTP {resp.status}: {error_text}",
                                error_code="CREATE_ERROR",
                                status_code=resp.status,
                            )
            except GrokApiException:
                raise
            except Exception as e:
                if attempt < 2:
                    logger.warning("[PostCreate] Attempt %d error: %s", attempt + 1, e)
                    await asyncio.sleep(1)
                    continue
                raise GrokApiException(
                    message=str(e),
                    error_code="CREATE_ERROR",
                    status_code=500,
                )

        raise GrokApiException(
            message="Max retries exceeded",
            error_code="CREATE_ERROR",
            status_code=500,
        )
