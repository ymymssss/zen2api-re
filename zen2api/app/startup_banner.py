"""Startup banner helpers for managed proxy services."""
from __future__ import annotations

import logging
import textwrap
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Optional

from .logger import get_logger

logger = get_logger("startup_banner")

_MIN_INNER_WIDTH = 60


@dataclass(frozen=True)
class PanelStyle:
    top_left: str
    top_right: str
    separator_left: str
    separator_right: str
    bottom_left: str
    bottom_right: str
    horizontal: str
    vertical: str


UNICODE_PANEL_STYLE = PanelStyle(
    top_left="┌",
    top_right="┐",
    separator_left="├",
    separator_right="┤",
    bottom_left="└",
    bottom_right="┘",
    horizontal="─",
    vertical="│",
)

ASCII_PANEL_STYLE = PanelStyle(
    top_left="+",
    top_right="+",
    separator_left="+",
    separator_right="+",
    bottom_left="+",
    bottom_right="+",
    horizontal="-",
    vertical="|",
)


def _format_row(text: str, width: int, style: PanelStyle) -> str:
    return f"{style.vertical} {text:<{width}} {style.vertical}"


def render_panel(
    title: str,
    rows: Sequence[str | None],
    min_inner_width: int = _MIN_INNER_WIDTH,
    style: PanelStyle = UNICODE_PANEL_STYLE,
) -> list[str]:
    """Render a boxed startup panel with optional section separators."""
    normalized_rows: list[str] = []
    for row in rows:
        if row is None:
            normalized_rows.append("")
        else:
            normalized_rows.append(row)

    visible_rows = [r for r in normalized_rows if r]
    width = max(
        min_inner_width,
        max((len(r) for r in visible_rows), default=0),
        len(title),
    )

    panels: list[str] = []
    panels.append(f"{style.top_left}{style.horizontal * (width + 2)}{style.top_right}")
    panels.append(_format_row(title.center(width), width, style))
    panels.append(f"{style.separator_left}{style.horizontal * (width + 2)}{style.separator_right}")

    for row in normalized_rows:
        if row == "":
            panels.append(
                f"{style.separator_left}{style.horizontal * (width + 2)}{style.separator_right}"
            )
            continue

        for line in textwrap.wrap(row, width) or [""]:
            panels.append(_format_row(line, width, style))

    panels.append(
        f"{style.bottom_left}{style.horizontal * (width + 2)}{style.bottom_right}"
    )

    return panels


def log_panel(
    panel_lines: list[str],
    panel_logger: logging.Logger | None = None,
) -> None:
    """Emit a rendered panel via logger.info line by line."""
    resolved = panel_logger or logger
    for line in panel_lines:
        resolved.info(line)


def resolve_panel_style(
    handlers: Iterable[logging.Handler] | None = None,
) -> PanelStyle:
    """Choose a banner style that is safe for all effective logger handlers."""
    encodings: set[str] = set()

    for handler in handlers or logging.getLogger().handlers:
        if hasattr(handler, "stream"):
            stream = getattr(handler, "stream", None)
            if stream and hasattr(stream, "encoding"):
                enc = getattr(stream, "encoding", None)
                if enc:
                    encodings.add(enc.lower())

    if encodings and all(
        "utf" in enc.replace("-", "").replace("_", "") for enc in encodings
    ):
        return UNICODE_PANEL_STYLE

    return ASCII_PANEL_STYLE


def build_zen2api_panel(
    host: str,
    port: int,
    auth_enabled: bool,
    build_label: str,
    model_discovery_enabled: bool,
    model_discovery_ttl_seconds: int,
    zen_models: Iterable[str],
    kilo_models: Iterable[str],
    non_modal_rps: int | None,
    stats_file: str,
    stats_log_interval: int,
    version: str,
    style: PanelStyle = UNICODE_PANEL_STYLE,
) -> list[str]:
    """Build startup rows for the main zen2api proxy."""
    base_url = f"http://{host}:{port}"

    zen_count = len(list(zen_models))
    kilo_count = len(list(kilo_models))

    auth_status = "enabled" if auth_enabled else "disabled"
    discovery_status = "ON" if model_discovery_enabled else "OFF"

    rows: list[str | None] = [
        f"Server: {base_url}",
        f"Build: {build_label}",
        f"Auth: {auth_status}",
        f"Models: auto-discovery={discovery_status}",
        None,
        "API Endpoints:",
        "- Anthropic: POST /v1/messages",
        "- OpenAI: POST /v1/chat/completions",
        "- Responses: POST /v1/responses",
        "- Models: GET /v1/models",
        "- Health: GET /health",
        None,
        "- Stats: GET /stats, POST /stats/reset",
        None,
        "Client Setup:",
        f"- Claude Code: ANTHROPIC_BASE_URL={base_url}",
        f"- OpenAI / Cursor IDE: OPENAI_BASE_URL={base_url}",
        "- Request auth: x-api-key or Authorization: Bearer",
        None,
        "Service Config:",
        "- Auth key env: ZEN2API_KEY",
        "- Listen env: ZEN2API_HOST, ZEN2API_PORT",
        f"- Manual model overrides: zen={zen_count}, kilo={kilo_count}",
        f"- Discovery cache TTL: {model_discovery_ttl_seconds}s",
        f"- Rate limit: ZEN2API_NON_MODAL_RPS={non_modal_rps or 'disabled'}",
        f"- Stats file: {stats_file}",
        f"- Stats log interval: {stats_log_interval}s",
    ]

    return render_panel(
        title=f"zen2api v{version}",
        rows=rows,
        style=style,
    )



