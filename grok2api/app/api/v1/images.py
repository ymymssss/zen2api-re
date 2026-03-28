from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.logger import logging
from app.services.grok.cache import image_cache_service, video_cache_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["Images"])


def _safe_cache_name(name: str) -> str:
    normalized = name.replace("..", "").replace("/", "").replace("\\", "")
    return normalized


def is_video(path: str) -> bool:
    video_extensions = [".mp4", ".webm", ".mov", ".avi"]
    return any(path.lower().endswith(ext) for ext in video_extensions)


@router.get("/{img_path:path}")
async def get_image(img_path: str):
    safe_name = _safe_cache_name(img_path)

    if is_video(safe_name):
        cache_dir = video_cache_service.cache_dir
    else:
        cache_dir = image_cache_service.cache_dir

    cache_path = Path(cache_dir) / safe_name

    if not cache_path.exists():
        return HTTPException(status_code=404, detail="File not found")

    if is_video(safe_name):
        media_type = "video/mp4"
    else:
        media_type = "image/jpeg"

    return FileResponse(
        path=str(cache_path),
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )
