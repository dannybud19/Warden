"""WebSocket stream of agent and orchestrator events."""

import asyncio

from fastapi import APIRouter, WebSocket

from app.contracts import AgentStarted, ScoreUpdated
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseNotFoundError, CaseService

router = APIRouter()


@router.websocket("/cases/{case_id}/stream")
async def stream(websocket: WebSocket, case_id: str) -> None:
    """Send the latest score on connect, then forward bus events until the client leaves."""
    service: CaseService = websocket.app.state.service
    bus: EventBus = websocket.app.state.bus
    try:
        case = await service.get_case(case_id)
    except CaseNotFoundError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = bus.subscribe(case_id)
    try:
        if case.score_history:
            await websocket.send_text(ScoreUpdated(score=case.score_history[-1]).model_dump_json())
        # NOTE: an analysis may have started before this client connected (the check now starts when
        # the home is added). Replay the agents still running so the UI shows them as working.
        # The queue is subscribed first, so an agent that finishes meanwhile is not missed.
        for agent in service.running_agents(case_id):
            await websocket.send_text(AgentStarted(agent=agent).model_dump_json())

        async def forward() -> None:
            while True:
                event = await queue.get()
                await websocket.send_text(event.model_dump_json())

        async def wait_for_disconnect() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return

        tasks = [asyncio.create_task(forward()), asyncio.create_task(wait_for_disconnect())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        bus.unsubscribe(case_id, queue)
