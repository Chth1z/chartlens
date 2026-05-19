"""In-memory pub/sub bus for case processing progress events.

Thread-safe: the pipeline runs in a ThreadPoolExecutor, so publish() is called
from worker threads while subscribe() yields events in an async context.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    """A single progress event for a case."""

    case_id: str
    stage: str
    step: str = ""
    progress: float = 0.0
    started_at: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "stage": self.stage,
            "step": self.step,
            "progress": self.progress,
            "started_at": self.started_at,
            "message": self.message,
        }


@dataclass
class _Subscription:
    queue: asyncio.Queue[ProgressEvent | None]
    loop: asyncio.AbstractEventLoop


class CaseProgressBus:
    """Simple in-memory pub/sub for case progress.

    - publish() is thread-safe (called from ThreadPoolExecutor workers).
    - subscribe() returns an async generator that yields ProgressEvent instances.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # case_id -> list of active subscriptions
        self._subscribers: dict[str, list[_Subscription]] = {}

    def publish(self, case_id: str, event: ProgressEvent) -> None:
        """Publish an event to all subscribers of a case. Thread-safe."""
        with self._lock:
            subs = self._subscribers.get(case_id, [])
            dead: list[_Subscription] = []
            for sub in subs:
                try:
                    sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
                except RuntimeError:
                    # Event loop closed; mark for removal
                    dead.append(sub)
            if dead:
                for d in dead:
                    subs.remove(d)

    async def subscribe(self, case_id: str) -> asyncio.Queue[ProgressEvent | None]:
        """Create a subscription queue for a case. Returns the queue.

        Send None to the queue to signal stream end.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        sub = _Subscription(queue=queue, loop=loop)
        with self._lock:
            self._subscribers.setdefault(case_id, []).append(sub)
        return queue

    def unsubscribe(self, case_id: str, queue: asyncio.Queue[ProgressEvent | None]) -> None:
        """Remove a subscription."""
        with self._lock:
            subs = self._subscribers.get(case_id, [])
            self._subscribers[case_id] = [s for s in subs if s.queue is not queue]
            if not self._subscribers[case_id]:
                del self._subscribers[case_id]

    def close_case(self, case_id: str) -> None:
        """Signal all subscribers that the case stream is done."""
        with self._lock:
            subs = self._subscribers.pop(case_id, [])
            for sub in subs:
                try:
                    sub.loop.call_soon_threadsafe(sub.queue.put_nowait, None)
                except RuntimeError:
                    pass


# Singleton instance
progress_bus = CaseProgressBus()
