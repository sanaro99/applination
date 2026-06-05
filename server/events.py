"""In-process pub/sub for pipeline events keyed by run_id."""
from __future__ import annotations
import asyncio
import json
from collections import defaultdict, deque
from typing import AsyncIterator


class EventBus:
    """Fan-out broker. One producer (the pipeline thread) per run_id, many
    consumers (SSE connections). Stores a bounded history so clients that
    connect mid-run get the catch-up before live events."""

    def __init__(self, history_per_run: int = 2000):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[int, deque[dict]] = defaultdict(
            lambda: deque(maxlen=history_per_run)
        )
        self._closed: set[int] = set()
        self._lock = asyncio.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish_threadsafe(self, run_id: int, event: dict) -> None:
        """Called from the worker thread running the pipeline."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._publish, run_id, event)

    def _publish(self, run_id: int, event: dict) -> None:
        self._history[run_id].append(event)
        for q in list(self._subscribers.get(run_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        if event.get("type") in ("done", "error", "cancelled"):
            self._closed.add(run_id)
            for q in list(self._subscribers.get(run_id, [])):
                try:
                    q.put_nowait(None)  # sentinel
                except asyncio.QueueFull:
                    pass

    async def subscribe(self, run_id: int) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self._subscribers[run_id].append(q)
        try:
            for past in list(self._history.get(run_id, [])):
                yield past
            if run_id in self._closed:
                return
            while True:
                evt = await q.get()
                if evt is None:
                    return
                yield evt
        finally:
            try:
                self._subscribers[run_id].remove(q)
            except ValueError:
                pass


bus = EventBus()


def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"
