"""In-process per-case pub/sub feeding the WebSocket."""

import asyncio
from collections import defaultdict

from app.contracts import StreamEvent


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[StreamEvent]]] = defaultdict(set)

    def subscribe(self, case_id: str) -> asyncio.Queue[StreamEvent]:
        """A new queue that receives every event published for this case."""
        q: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._subs[case_id].add(q)
        return q

    def unsubscribe(self, case_id: str, q: asyncio.Queue[StreamEvent]) -> None:
        """Stop delivering events to this queue."""
        self._subs[case_id].discard(q)

    async def publish(self, case_id: str, event: StreamEvent) -> None:
        """Deliver an event to every subscriber of the case."""
        for q in list(self._subs[case_id]):
            q.put_nowait(event)
