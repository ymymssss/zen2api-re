"""MCP (Model Context Protocol) server implementation."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from ...core.config import setting
from ...core.logger import logger


class MCPServer:
    """MCP server for tool integration."""

    def __init__(self):
        self._tools = {}
        self._connections = []

    def register_tool(self, name: str, handler, description: str = ""):
        """Register a tool handler."""
        self._tools[name] = {
            "handler": handler,
            "description": description,
        }
        logger.debug(f"[MCP] Registered tool: {name}")

    async def handle_connection(self, websocket: WebSocket):
        """Handle a WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                response = await self._handle_message(data)
                await websocket.send_json(response)
        except Exception as e:
            logger.debug(f"[MCP] Connection closed: {e}")
        finally:
            self._connections.remove(websocket)

    async def _handle_message(self, message: Dict) -> Dict:
        """Handle an incoming MCP message."""
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "tools/list":
            return {
                "tools": [
                    {"name": name, "description": info["description"]}
                    for name, info in self._tools.items()
                ]
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            if tool_name in self._tools:
                try:
                    result = await self._tools[tool_name]["handler"](params)
                    return {"result": result}
                except Exception as e:
                    return {"error": str(e)}
            return {"error": f"Tool not found: {tool_name}"}

        return {"error": f"Unknown method: {method}"}


# Singleton instance
mcp_server = MCPServer()
