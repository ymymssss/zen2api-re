"""Rate limiter implementation with slot-based concurrency control."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Optional

from .logger import get_logger

logger = get_logger("rate_limiter")


def build_rps_slots(requests_per_second: int, prefix: str = "") -> list[str]:
    """Build slot names for rate limiter."""
    return [f"{prefix}{i}" for i in range(requests_per_second)]


class SlotRateLimiter:
    """Slot-based rate limiter with minimum interval enforcement."""

    def __init__(
        self,
        slots: Sequence[str],
        min_interval_sec: float = 0.0,
        empty_error_message: str = "rate limiter has no slots configured",
    ):
        self._slots: list[str] = list(slots)
        self._min_interval_sec = min_interval_sec
        self._empty_error_message = empty_error_message
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._slot_locks: dict[str, asyncio.Lock] = {}
        self._slot_last_request_time: dict[str, float] = {}

        for slot in self._slots:
            self._queue.put_nowait(slot)
            self._slot_locks[slot] = asyncio.Lock()
            self._slot_last_request_time[slot] = 0.0

    def reconfigure(
        self,
        slots: Sequence[str],
        min_interval_sec: Optional[float] = None,
    ) -> None:
        """Reconfigure the rate limiter with new slots."""
        self._slots = list(slots)
        if min_interval_sec is not None:
            self._min_interval_sec = min_interval_sec

        # Rebuild queue and locks
        self._queue = asyncio.Queue()
        self._slot_locks = {}
        self._slot_last_request_time = {}

        for slot in self._slots:
            self._queue.put_nowait(slot)
            self._slot_locks[slot] = asyncio.Lock()
            self._slot_last_request_time[slot] = 0.0

    async def acquire(self) -> str:
        """Acquire a rate limiter slot."""
        if not self._slots:
            raise RuntimeError(self._empty_error_message)

        slot = await self._queue.get()
        lock = self._slot_locks[slot]

        async with lock:
            import time

            now = time.monotonic()
            elapsed = now - self._slot_last_request_time[slot]

            if elapsed < self._min_interval_sec:
                try:
                    await asyncio.sleep(self._min_interval_sec - elapsed)
                except Exception:
                    pass

            self._slot_last_request_time[slot] = time.monotonic()

        return slot

    async def release(self, slot: str) -> None:
        """Release a rate limiter slot back to the queue."""
        try:
            self._queue.put_nowait(slot)
        except asyncio.QueueFull:
            logger.error(
                "Failed to release slot=%s: queue is full (possible double release)",
                slot,
            )

    @property
    def queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()
