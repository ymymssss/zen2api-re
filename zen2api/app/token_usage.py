"""Utilities for normalizing token usage across upstream providers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


def _to_int(value: Any) -> int:
    """Convert value to int, handling None and invalid types."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def normalized(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=max(0, self.input_tokens),
            output_tokens=max(0, self.output_tokens),
            cached_input_tokens=max(0, self.cached_input_tokens),
        )

    def add(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )

    @property
    def is_empty(self) -> bool:
        return (
            self.input_tokens == 0
            and self.output_tokens == 0
            and self.cached_input_tokens == 0
        )

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def cache_hit_rate(self) -> float:
        if self.input_tokens <= 0:
            return 0.0
        return min(1.0, self.cached_input_tokens / self.input_tokens)


def parse_anthropic_usage(usage: dict[str, Any] | None) -> TokenUsage:
    """Parse Anthropic API usage response."""
    if not usage or not isinstance(usage, dict):
        return TokenUsage()

    cache_read = _to_int(usage.get("cache_read_input_tokens"))
    cache_creation = _to_int(usage.get("cache_creation_input_tokens"))
    base_input = _to_int(usage.get("input_tokens"))
    cached_input = cache_read + cache_creation

    return TokenUsage(
        input_tokens=base_input,
        output_tokens=_to_int(usage.get("output_tokens")),
        cached_input_tokens=cached_input,
    )


def parse_openai_usage(usage: dict[str, Any] | None) -> TokenUsage:
    """Parse OpenAI API usage response."""
    if not usage or not isinstance(usage, dict):
        return TokenUsage()

    prompt_details = usage.get("prompt_tokens_details") or {}
    cached_tokens = _to_int(prompt_details.get("cached_tokens"))

    return TokenUsage(
        input_tokens=_to_int(usage.get("prompt_tokens")),
        output_tokens=_to_int(usage.get("completion_tokens")),
        cached_input_tokens=cached_tokens,
    )


def parse_responses_usage(usage: dict[str, Any] | None) -> TokenUsage:
    """Parse OpenAI Responses API usage."""
    if not usage or not isinstance(usage, dict):
        return TokenUsage()

    input_details = usage.get("input_tokens_details") or {}
    cached_tokens = _to_int(input_details.get("cached_tokens"))

    return TokenUsage(
        input_tokens=_to_int(usage.get("input_tokens")),
        output_tokens=_to_int(usage.get("output_tokens")),
        cached_input_tokens=cached_tokens,
    )


def extract_anthropic_sse_usage(message: str) -> TokenUsage:
    """Extract token usage from Anthropic SSE stream."""
    total = TokenUsage()
    for obj in _iter_sse_objects(message):
        usage = obj.get("usage")
        if usage:
            parsed = parse_anthropic_usage(usage)
            total = total.add(parsed)
    return total


def extract_openai_sse_usage(message: str) -> TokenUsage:
    """Extract token usage from OpenAI SSE stream."""
    total = TokenUsage()
    for obj in _iter_sse_objects(message):
        usage = obj.get("usage")
        if usage:
            parsed = parse_openai_usage(usage)
            total = total.add(parsed)
    return total


def _iter_sse_objects(message: str):
    """Iterate over SSE data payloads as JSON objects."""
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data: "):
            continue
        payload = stripped[6:]
        if payload == "[DONE]":
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue
