"""Request header management for upstream providers."""
from __future__ import annotations

from typing import Optional
from uuid import uuid4

from . import config

_SESSION_ID: Optional[str] = None


def get_session_id() -> str:
    """Get or create session ID."""
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = uuid4().hex
    return _SESSION_ID


def make_request_id() -> str:
    """Generate a unique request ID."""
    return uuid4().hex


def build_zen_headers(
    api_key: Optional[str] = None,
    anthropic_version: Optional[str] = None,
) -> dict[str, str]:
    """Build headers for Zen Anthropic upstream."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key or "",
        "User-Agent": config.ZEN_USER_AGENT,
        "anthropic-version": anthropic_version or config.ZEN_ANTHROPIC_VERSION,
        "x-opencode-client": "global",
        "x-opencode-project": "zen2api",
        "x-opencode-session": get_session_id(),
        "x-opencode-request": make_request_id(),
    }
    return headers


def build_kilo_headers(api_key: Optional[str] = None) -> dict[str, str]:
    """Build headers for Kilo OpenRouter upstream."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key or 'anonymous'}",
        "HTTP-Referer": "https://kilocode.ai",
        "X-KILOCODE-EDITORNAME": "Kilo CLI",
        "X-KILOCODE-FEATURE": "opencode-kilo-provider",
        "X-KILOCODE-PROJECTID": "zen2api",
        "X-KILOCODE-TASKID": make_request_id(),
        "X-Title": "Kilo Code",
        "x-kilocode-mode": "code",
    }
    return headers
