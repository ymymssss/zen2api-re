"""Responses API adapter for transforming between Chat Completions and Responses formats."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional
from uuid import uuid4


def transform_responses_request_to_chat(responses_body: dict[str, Any]) -> dict[str, Any]:
    """Transform OpenAI Responses API request to Chat Completions format."""
    model = responses_body.get("model")
    if not model:
        raise ValueError("`model` is required")

    instructions = responses_body.get("instructions")
    input_data = responses_body.get("input")
    if not input_data and not instructions:
        raise ValueError("`input` or `instructions` is required")

    messages: list[dict[str, Any]] = []

    if instructions:
        if isinstance(instructions, str):
            messages.append({"role": "system", "content": instructions})
        elif isinstance(instructions, list):
            text_parts = _convert_input_to_chat_messages(instructions)
            if text_parts:
                messages.append({"role": "system", "content": "\n".join(text_parts)})

    if input_data:
        if isinstance(input_data, str):
            messages.append({"role": "user", "content": input_data})
        elif isinstance(input_data, list):
            converted = _convert_input_to_messages(input_data)
            messages.extend(converted)

    chat_body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    stream = responses_body.get("stream")
    if stream:
        chat_body["stream"] = True

    max_output = responses_body.get("max_output_tokens")
    if max_output:
        chat_body["max_tokens"] = max_output

    tools = responses_body.get("tools")
    if tools and isinstance(tools, list):
        chat_tools = _convert_tools(tools)
        if chat_tools:
            chat_body["tools"] = chat_tools

    tool_choice = responses_body.get("tool_choice")
    if tool_choice:
        converted = _convert_tool_choice(tool_choice)
        if converted:
            chat_body["tool_choice"] = converted

    text_format = responses_body.get("text")
    if text_format and isinstance(text_format, dict):
        fmt = text_format.get("format", {})
        if isinstance(fmt, dict):
            fmt_type = fmt.get("type")
            if fmt_type == "json_object":
                chat_body["response_format"] = {"type": "json_object"}
            elif fmt_type == "json_schema":
                schema = fmt.get("schema", {})
                chat_body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": fmt.get("name", "response"),
                        "strict": fmt.get("strict", False),
                        "schema": schema,
                    },
                }

    passthrough_fields = [
        "temperature", "top_p", "metadata", "user", "store",
        "service_tier", "parallel_tool_calls",
    ]
    for field in passthrough_fields:
        if field in responses_body:
            chat_body[field] = responses_body[field]

    return chat_body


def transform_chat_response_to_responses(
    chat_resp: dict[str, Any],
    source_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transform Chat Completions response to Responses API format."""
    choices = chat_resp.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})
    usage = chat_resp.get("usage", {})

    output_text = _extract_text_from_chat_message_content(message.get("content"))
    output_items = [_build_response_message_item(message, output_text)]

    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        output_items.append(_build_response_function_call_item(tc))

    chat_usage = _build_response_usage(usage)

    return _build_response_payload(
        chat_resp=chat_resp,
        output_items=output_items,
        output_text=output_text,
        usage=chat_usage,
        source_request=source_request,
    )


async def stream_chat_to_responses(
    chat_stream: AsyncIterator[bytes],
) -> AsyncIterator[bytes]:
    """Convert Chat Completions SSE stream to Responses API SSE format."""
    msg_id = f"resp_{uuid4().hex[:24]}"
    sequence_number = 0

    def next_sequence() -> int:
        nonlocal sequence_number
        seq = sequence_number
        sequence_number += 1
        return seq

    def _sse_data(event: str, data: dict[str, Any]) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")

    text_chunks: list[str] = []
    usage_obj: dict[str, Any] | None = None
    created_emitted = False
    text_started = False
    message_item_id = f"msg_{uuid4().hex[:24]}"

    async for chunk in chat_stream:
        text = chunk.decode("utf-8", errors="ignore")
        for payload in _iter_sse_payloads(text):
            if payload.get("error"):
                yield _sse_data(
                    "error",
                    {
                        "type": "error",
                        "code": payload["error"].get("type", "upstream error"),
                        "message": payload["error"].get("message", "unknown error"),
                        "param": None,
                        "sequence_number": next_sequence(),
                    },
                )
                continue

            if not created_emitted:
                yield _sse_data(
                    "response.created",
                    {
                        "type": "response.created",
                        "sequence_number": next_sequence(),
                        "response": {
                            "id": msg_id,
                            "object": "response",
                            "created_at": _now_iso(),
                            "status": "in_progress",
                            "model": payload.get("model", "unknown"),
                        },
                    },
                )
                yield _sse_data(
                    "response.in_progress",
                    {
                        "type": "response.in_progress",
                        "sequence_number": next_sequence(),
                        "response": {
                            "id": msg_id,
                            "object": "response",
                            "created_at": _now_iso(),
                            "status": "in_progress",
                            "model": payload.get("model", "unknown"),
                        },
                    },
                )
                created_emitted = True

            delta = payload.get("delta", {})
            choices = payload.get("choices", [])
            choice = choices[0] if choices else {}

            if delta.get("content"):
                if not text_started:
                    yield _sse_data(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "sequence_number": next_sequence(),
                            "item": {
                                "id": message_item_id,
                                "type": "message",
                                "role": "assistant",
                                "status": "in_progress",
                            },
                            "output_index": 0,
                        },
                    )
                    yield _sse_data(
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "sequence_number": next_sequence(),
                            "item_id": message_item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                            },
                        },
                    )
                    text_started = True

                text_chunks.append(delta["content"])
                yield _sse_data(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "sequence_number": next_sequence(),
                        "item_id": message_item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": delta["content"],
                        "logprobs": None,
                        "index": 0,
                    },
                )

            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    func = tc.get("function", {})
                    tc_id = tc.get("id", f"fc_{uuid4().hex[:24]}")
                    tc_name = func.get("name", "unknown_function")
                    tc_args = func.get("arguments", "")

                    if func.get("name"):
                        yield _sse_data(
                            "response.output_item.added",
                            {
                                "type": "response.output_item.added",
                                "sequence_number": next_sequence(),
                                "item": {
                                    "id": tc_id,
                                    "type": "function_call",
                                    "status": "in_progress",
                                    "name": tc_name,
                                    "arguments": "",
                                    "call_id": tc_id,
                                },
                                "output_index": 1,
                            },
                        )
                    elif tc_args:
                        yield _sse_data(
                            "response.output_text.delta",
                            {
                                "type": "response.output_text.delta",
                                "sequence_number": next_sequence(),
                                "item_id": tc_id,
                                "output_index": 1,
                                "content_index": 0,
                                "delta": tc_args,
                                "logprobs": None,
                                "index": 0,
                            },
                        )

            if choice.get("finish_reason") == "stop" and text_started:
                final_text = "".join(text_chunks)
                yield _sse_data(
                    "response.output_text.done",
                    {
                        "type": "response.output_text.done",
                        "sequence_number": next_sequence(),
                        "item_id": message_item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": final_text,
                    },
                )
                yield _sse_data(
                    "response.content_part.done",
                    {
                        "type": "response.content_part.done",
                        "sequence_number": next_sequence(),
                        "item_id": message_item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": final_text,
                            "annotations": [],
                        },
                    },
                )
                yield _sse_data(
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "sequence_number": next_sequence(),
                        "item": {
                            "id": message_item_id,
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": final_text,
                        },
                        "output_index": 0,
                    },
                )

            if payload.get("usage"):
                usage_obj = payload["usage"]

    if usage_obj:
        yield _sse_data(
            "response.completed",
            {
                "type": "response.completed",
                "sequence_number": next_sequence(),
                "response": {
                    "id": msg_id,
                    "object": "response",
                    "created_at": _now_iso(),
                    "status": "completed",
                    "model": "unknown",
                    "output": [],
                    "usage": _build_response_usage(usage_obj),
                },
            },
        )

    yield b"data: [DONE]\n\n"


def _convert_input_to_chat_messages(input_data: list[Any]) -> list[str]:
    """Convert input list to chat message text."""
    parts: list[str] = []
    for item in input_data:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "message":
                content = item.get("content", "")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "input_text":
                            parts.append(part.get("text", ""))
    return parts


def _convert_input_to_messages(input_data: list[Any]) -> list[dict[str, Any]]:
    """Convert input list to chat messages."""
    messages: list[dict[str, Any]] = []
    for item in input_data:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
        elif isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "function_call_output":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("call_id", ""),
                        "content": item.get("output", ""),
                    }
                )
            elif item_type == "message":
                role = item.get("role", "user")
                content = item.get("content", "")
                if role == "developer":
                    messages.append({"role": "system", "content": content})
                elif role in ("user", "assistant"):
                    messages.append({"role": role, "content": content})
                else:
                    raise ValueError(f"unsupported message role: {role}")
            else:
                raise ValueError(f"unsupported input item type: {item_type}")
    return messages


def _convert_message_content(content: Any) -> list[dict[str, Any]]:
    """Convert message content to chat format."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        raise ValueError("message content must be a string or a list")

    chat_parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ValueError("message content item must be an object")
        item_type = item.get("type")
        if item_type == "input_text":
            chat_parts.append({"type": "text", "text": item.get("text", "")})
        elif item_type == "input_image":
            image_url = item.get("image_url")
            if not image_url:
                raise ValueError("`input_image.image_url` is required")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if not url:
                raise ValueError("`image_url.url` is required")
            chat_parts.append({"type": "image_url", "image_url": {"url": url}})
        else:
            raise ValueError(f"unsupported message content type: {item_type}")
    return chat_parts


def _convert_tools(tools: list[Any]) -> list[dict[str, Any]]:
    """Convert Responses API tools to Chat Completions format."""
    if not isinstance(tools, list):
        raise ValueError("`tools` must be a list")

    chat_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("tool must be an object")
        tool_type = tool.get("type", "function")
        if tool_type != "function":
            raise ValueError(f"unsupported tool type for chat/completions: {tool_type}")
        name = tool.get("name")
        if not name:
            raise ValueError("function tool requires `name`")
        chat_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                },
            }
        )
    return chat_tools


def _convert_tool_choice(tool_choice: Any) -> Any:
    """Convert Responses API tool_choice to Chat Completions format."""
    if isinstance(tool_choice, str):
        if tool_choice in ("auto", "none", "required"):
            return tool_choice
        raise ValueError(f"unsupported tool_choice value: {tool_choice}")

    if isinstance(tool_choice, dict):
        choice_type = tool_choice.get("type")
        if choice_type == "function":
            name = tool_choice.get("name")
            if not name:
                raise ValueError("`tool_choice.name` is required for function tool choice")
            return {"type": "function", "function": {"name": name}}
        raise ValueError(f"unsupported tool_choice type: {choice_type}")

    raise ValueError("unsupported tool_choice")


def _extract_text_from_chat_message_content(content: Any) -> str:
    """Extract text from chat message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        all_text = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                all_text.append(part.get("text", ""))
        return "\n".join(all_text)
    return ""


def _build_response_message_item(
    message: dict[str, Any], output_text: str
) -> dict[str, Any]:
    """Build a response message item."""
    return {
        "id": f"msg_{uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": output_text,
    }


def _build_response_function_call_item(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Build a response function call item."""
    func = tool_call.get("function", {})
    return {
        "id": tool_call.get("id", f"fc_{uuid4().hex[:24]}"),
        "type": "function_call",
        "status": "completed",
        "name": func.get("name", ""),
        "arguments": func.get("arguments", ""),
        "call_id": tool_call.get("id", ""),
    }


def _build_response_usage(usage: dict[str, Any]) -> dict[str, Any]:
    """Build response usage object."""
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}

    return {
        "input_tokens": usage.get("prompt_tokens", 0),
        "input_tokens_details": {
            "cached_tokens": prompt_details.get("cached_tokens", 0),
        },
        "output_tokens": usage.get("completion_tokens", 0),
        "output_tokens_details": {
            "reasoning_tokens": completion_details.get("reasoning_tokens", 0),
        },
        "total_tokens": usage.get("total_tokens", 0),
    }


def _build_response_payload(
    chat_resp: dict[str, Any],
    output_items: list[dict[str, Any]],
    output_text: str,
    usage: dict[str, Any],
    source_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build full response payload."""
    import time

    return {
        "id": f"resp_{uuid4().hex[:24]}",
        "object": "response",
        "created_at": _now_iso(),
        "status": "completed",
        "background": False,
        "model": chat_resp.get("model", "unknown"),
        "output": output_items,
        "output_text": output_text,
        "temperature": (source_request or {}).get("temperature"),
        "top_p": (source_request or {}).get("top_p"),
        "max_output_tokens": (source_request or {}).get("max_output_tokens"),
        "previous_response_id": (source_request or {}).get("previous_response_id"),
        "reasoning": (source_request or {}).get("reasoning"),
        "tool_choice": (source_request or {}).get("tool_choice", "auto"),
        "truncation": (source_request or {}).get("truncation", "disabled"),
        "usage": usage,
    }


def _now_iso() -> str:
    """Get current time in ISO format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _iter_sse_payloads(text: str):
    """Iterate over SSE payloads as JSON objects."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data: "):
            continue
        payload_raw = stripped[6:]
        if payload_raw == "[DONE]":
            continue
        try:
            yield json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
