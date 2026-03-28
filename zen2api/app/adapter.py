"""Adapter for transforming between Anthropic and OpenAI formats."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from .token_usage import TokenUsage, parse_anthropic_usage, parse_openai_usage


def normalize_model_name(model: str) -> str:
    """Normalize model name."""
    return model.strip()


def _convert_image_source(source: dict[str, Any]) -> dict[str, Any]:
    """Convert Anthropic image source to OpenAI image_url."""
    if source.get("type") == "base64":
        media_type = source.get("media_type", "image/png")
        data = source.get("data", "")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{data}"},
        }
    return source


def transform_request_body(anthropic_body: dict[str, Any]) -> dict[str, Any]:
    """Transform Anthropic v1/messages request to OpenAI v1/chat/completions."""
    messages: list[dict[str, Any]] = []

    system = anthropic_body.get("system")
    if system:
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            text_parts = [
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if text_parts:
                messages.append({"role": "system", "content": "\n".join(text_parts)})

    for msg in anthropic_body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "user":
            if isinstance(content, str):
                messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                openai_content: list[dict[str, Any]] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text":
                        openai_content.append(
                            {"type": "text", "text": block.get("text", "")}
                        )
                    elif block_type == "image":
                        openai_content.append(_convert_image_source(block.get("source", {})))
                    elif block_type == "tool_result":
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, list):
                            tool_content = json.dumps(tool_content)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": tool_content,
                            }
                        )
                if openai_content:
                    messages.append({"role": "user", "content": openai_content})
        elif role == "assistant":
            if isinstance(content, str):
                messages.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text":
                        text_parts.append(block.get("text", ""))
                    elif block_type == "tool_use":
                        tool_calls.append(
                            {
                                "id": block.get("id", f"toolu_{uuid4().hex[:24]}"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            }
                        )
                msg_dict: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) if text_parts else None,
                }
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                messages.append(msg_dict)

    openai_body: dict[str, Any] = {
        "model": anthropic_body.get("model", "unknown"),
        "messages": messages,
    }

    if anthropic_body.get("stream"):
        openai_body["stream"] = True
    if anthropic_body.get("max_tokens"):
        openai_body["max_completion_tokens"] = anthropic_body["max_tokens"]
    if anthropic_body.get("temperature") is not None:
        openai_body["temperature"] = anthropic_body["temperature"]
    if anthropic_body.get("stop_sequences"):
        openai_body["stop"] = anthropic_body["stop_sequences"]
    if anthropic_body.get("top_p") is not None:
        openai_body["top_p"] = anthropic_body["top_p"]

    tools = anthropic_body.get("tools")
    if tools and isinstance(tools, list):
        openai_tools: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {}),
                    },
                }
            )
        if openai_tools:
            openai_body["tools"] = openai_tools

    tool_choice = anthropic_body.get("tool_choice")
    if tool_choice:
        if isinstance(tool_choice, str):
            if tool_choice in ("auto", "any"):
                openai_body["tool_choice"] = tool_choice
            elif tool_choice == "required":
                openai_body["tool_choice"] = "required"
        elif isinstance(tool_choice, dict):
            choice_type = tool_choice.get("type")
            if choice_type == "auto":
                openai_body["tool_choice"] = "auto"
            elif choice_type == "any":
                openai_body["tool_choice"] = "required"
            elif choice_type == "tool":
                name = tool_choice.get("name", "")
                if name:
                    openai_body["tool_choice"] = {
                        "type": "function",
                        "function": {"name": name},
                    }

    return openai_body


def transform_openai_response(openai_resp: dict[str, Any]) -> dict[str, Any]:
    """Transform OpenAI chat/completions response to Anthropic Messages."""
    choices = openai_resp.get("choices", [])
    if not choices:
        content_blocks: list[dict[str, Any]] = []
    else:
        choice = choices[0]
        message = choice.get("message", {})
        content_text = message.get("content", "") or ""
        content_blocks = [{"type": "text", "text": content_text}]

        tool_calls = message.get("tool_calls") or []
        for tc in tool_calls:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, ValueError):
                args = {}
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id", f"toolu_{uuid4().hex[:24]}"),
                    "name": func.get("name", ""),
                    "input": args,
                }
            )

    usage = openai_resp.get("usage", {})
    anthropic_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
    cache_read = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cache_read:
        anthropic_usage["cache_read_input_tokens"] = cache_read

    finish_reason = "end_turn"
    if choices:
        fr = choices[0].get("finish_reason", "stop")
        if fr == "length":
            finish_reason = "length"
        elif fr == "tool_calls":
            finish_reason = "tool_use"

    return {
        "id": openai_resp.get("id", f"chatcmpl-{uuid4().hex[:24]}"),
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": openai_resp.get("model", "unknown"),
        "stop_reason": finish_reason,
        "stop_sequence": None,
        "usage": anthropic_usage,
    }


def stream_openai_to_anthropic(openai_stream: bytes) -> AsyncIterator[dict[str, Any]]:
    """Convert OpenAI SSE stream to Anthropic SSE events.

    Note: This is a placeholder - actual implementation uses async iteration.
    """
    raise NotImplementedError("Use async version")


async def _iter_anthropic_sse_events(sse_text: str):
    """Iterate over Anthropic SSE events."""
    current_event = None
    data_lines: list[str] = []

    for raw_line in sse_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current_event and data_lines:
                payload_raw = "\n".join(data_lines)
                try:
                    payload_obj = json.loads(payload_raw)
                except json.JSONDecodeError:
                    payload_obj = None
                if payload_obj is not None:
                    yield current_event, payload_obj
            current_event = None
            data_lines = []
            continue

        if stripped.startswith("event: "):
            current_event = stripped[7:].strip()
        elif stripped.startswith("data: "):
            data_lines.append(stripped[6:])

    if current_event and data_lines:
        payload_raw = "\n".join(data_lines)
        try:
            payload_obj = json.loads(payload_raw)
            yield current_event, payload_obj
        except json.JSONDecodeError:
            pass


def _openai_sse_error(error_type: str, error_msg: str) -> str:
    """Format OpenAI SSE error event."""
    return f"data: {json.dumps({'error': {'type': error_type, 'message': error_msg}})}\n\n"


def _openai_sse_chunk(chunk: dict[str, Any]) -> str:
    """Format OpenAI SSE chunk."""
    return f"data: {json.dumps(chunk)}\n\n"


def stream_anthropic_to_openai(
    sse_text: str,
) -> str:
    """Convert Anthropic SSE stream to OpenAI SSE format."""
    completion_id = f"chatcmpl-{uuid4().hex[:24]}"
    tool_index_map: dict[str, int] = {}
    next_tool_index = 0
    finish_emitted = False

    chunks: list[str] = []

    for event_name, payload in _iter_anthropic_sse_events(sse_text):
        if event_name == "error":
            err_obj = payload.get("error", {})
            err_type = err_obj.get("type", "api_error")
            err_msg = err_obj.get("message", "unknown error")
            chunks.append(_openai_sse_error(err_type, err_msg))
            continue

        if event_name == "message_start":
            msg = payload.get("message", {})
            chunk = {
                "id": msg.get("id", completion_id),
                "object": "chat.completion.chunk",
                "created": 0,
                "model": msg.get("model", "unknown"),
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            chunks.append(_openai_sse_chunk(chunk))
            continue

        if event_name == "content_block_start":
            block = payload.get("content_block", {})
            block_type = block.get("type")
            if block_type == "tool_use":
                tool_id = block.get("id", "")
                tool_name = block.get("name", "")
                if tool_id not in tool_index_map:
                    tool_index_map[tool_id] = next_tool_index
                    next_tool_index += 1
                tool_index = tool_index_map[tool_id]
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "unknown",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": tool_index,
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {"name": tool_name, "arguments": ""},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                chunks.append(_openai_sse_chunk(chunk))
            continue

        if event_name == "content_block_delta":
            delta = payload.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "unknown",
                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                }
                chunks.append(_openai_sse_chunk(chunk))
            elif delta_type == "input_json_delta":
                partial_json = delta.get("partial_json", "")
                target_index = payload.get("index", 0)
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "unknown",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": target_index,
                                        "function": {"arguments": partial_json},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                chunks.append(_openai_sse_chunk(chunk))
            continue

        if event_name == "message_delta":
            delta = payload.get("delta", {})
            stop_reason = delta.get("stop_reason", "")
            if stop_reason == "end_turn" and not finish_emitted:
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "unknown",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                chunks.append(_openai_sse_chunk(chunk))
                finish_emitted = True
            elif stop_reason == "tool_use" and not finish_emitted:
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "unknown",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                }
                chunks.append(_openai_sse_chunk(chunk))
                finish_emitted = True
            continue

        if event_name == "message_stop" and not finish_emitted:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "unknown",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            chunks.append(_openai_sse_chunk(chunk))
            finish_emitted = True

    chunks.append("data: [DONE]\n\n")
    return "\n".join(chunks)
