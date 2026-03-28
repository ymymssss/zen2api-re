"""MCP tool definitions and handlers."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from ...core.logger import logger
from .server import mcp_server


async def handle_bash(params: Dict) -> str:
    """Execute a bash command."""
    import subprocess
    command = params.get("command", "")
    if not command:
        return "No command provided"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or result.stderr or "No output"
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"


async def handle_read_file(params: Dict) -> str:
    """Read a file."""
    path = params.get("path", "")
    if not path:
        return "No path provided"
    try:
        from pathlib import Path
        return Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return f"Error: {e}"


async def handle_write_file(params: Dict) -> str:
    """Write to a file."""
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return "No path provided"
    try:
        from pathlib import Path
        Path(path).write_text(content, encoding="utf-8")
        return "OK"
    except Exception as e:
        return f"Error: {e}"


def register_default_tools():
    """Register default MCP tools."""
    mcp_server.register_tool(
        "bash",
        handle_bash,
        "Execute bash commands",
    )
    mcp_server.register_tool(
        "read_file",
        handle_read_file,
        "Read file contents",
    )
    mcp_server.register_tool(
        "write_file",
        handle_write_file,
        "Write file contents",
    )
    logger.debug("[MCP Tools] Default tools registered")


# Auto-register on import
register_default_tools()
