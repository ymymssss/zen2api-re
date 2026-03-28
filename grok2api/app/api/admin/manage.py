"""Admin API for token and key management."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from ...core.config import setting
from ...core.logger import logger
from ...core.paths import TEMPLATE_DIR, TEMP_ROOT, ensure_runtime_dirs
from ...services.grok.token import token_manager, TokenType
from ...services.request_stats import request_stats

router = APIRouter(tags=["admin"])


class LoginRequest:
    username: str
    password: str


@router.get("/")
async def admin_dashboard():
    """Admin dashboard."""
    return HTMLResponse("<h1>Grok2API Admin</h1>")


@router.get("/tokens")
async def list_tokens():
    """List all tokens."""
    return {"tokens": token_manager.list_tokens()}


@router.post("/tokens/add")
async def add_token(token_data: Dict):
    """Add a new token."""
    token = token_data.get("token", "")
    token_type = token_data.get("type", "cookie")
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")
    token_manager.add_token(token, TokenType(token_type))
    return {"status": "ok"}


@router.delete("/tokens/{token_id}")
async def remove_token(token_id: str):
    """Remove a token."""
    token_manager.remove_token(token_id)
    return {"status": "ok"}


@router.get("/stats")
async def get_stats():
    """Get request statistics."""
    return request_stats.get_stats()


@router.post("/stats/reset")
async def reset_stats():
    """Reset request statistics."""
    request_stats.reset()
    return {"status": "ok"}
