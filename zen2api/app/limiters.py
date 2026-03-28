"""Rate limiter configuration."""
from __future__ import annotations

from typing import Optional

from . import config
from .rate_limiter import SlotRateLimiter, build_rps_slots


def _create_non_modal_limiter() -> Optional[SlotRateLimiter]:
    """Create non-modal rate limiter from config."""
    if config.NON_MODAL_RPS is None or config.NON_MODAL_RPS <= 0:
        return None

    slots = build_rps_slots(config.NON_MODAL_RPS, prefix="non-modal")
    return SlotRateLimiter(
        slots=slots,
        min_interval_sec=1.0 / config.NON_MODAL_RPS,
        empty_error_message="Non-modal rate limiter slots are not configured",
    )


non_modal_limiter: Optional[SlotRateLimiter] = _create_non_modal_limiter()
