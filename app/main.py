from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_config
from app.models.schemas import RunLogResponse, RunRequest, RunSummary
from app.services.run_manager import RunManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.run_manager = RunManager(config)
    yield


app = FastAPI(title="Jellyfin Torrent Organizer", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs", response_model=RunSummary, status_code=202)
async def start_run(request: RunRequest) -> RunSummary:
    manager: RunManager = app.state.run_manager
    return await manager.start_run(request)


@app.get("/runs/current", response_model=RunSummary)
async def get_current_run() -> RunSummary:
    manager: RunManager = app.state.run_manager
    current = manager.get_current_run()
    if not current:
        raise HTTPException(status_code=404, detail="No runs have been started yet")
    return current


@app.get("/runs/current/logs", response_model=RunLogResponse)
async def get_current_run_logs() -> RunLogResponse:
    manager: RunManager = app.state.run_manager
    current = manager.get_current_run_logs()
    if not current:
        raise HTTPException(status_code=404, detail="No runs have been started yet")
    return current


@app.get("/logs")
async def stream_current_logs() -> StreamingResponse:
    async def event_stream():
        manager: RunManager = app.state.run_manager
        last_seen: str | None = None

        while True:
            current = manager.get_current_run()
            if not current:
                payload = '{"status":"idle","message":"No runs have been started yet"}'
                yield f"event: status\ndata: {payload}\n\n"
                await asyncio.sleep(1)
                continue

            snapshot = current.model_dump_json()
            if snapshot != last_seen:
                yield f"event: current\ndata: {snapshot}\n\n"
                last_seen = snapshot

            if current.status in {"completed", "failed", "cancelled"}:
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/runs/current/ai")
async def stream_current_ai() -> StreamingResponse:
    async def ai_stream():
        manager: RunManager = app.state.run_manager
        last_run_id: str | None = None
        last_step: str | None = None
        last_item_path: str | None = None
        last_thinking = ""
        last_output = ""

        while True:
            state = manager.get_current_run_state()
            if not state:
                await asyncio.sleep(0.5)
                continue

            if state.run_id != last_run_id or state.active_step != last_step or state.active_item_path != last_item_path:
                header = (
                    f"\n\n--- run={state.run_id} step={state.active_step or '-'} "
                    f"item={state.active_item_path or '-'} ---\n"
                )
                yield header
                last_run_id = state.run_id
                last_step = state.active_step
                last_item_path = state.active_item_path
                last_thinking = ""
                last_output = ""

            current_thinking = state.ai_thinking or ""
            if len(current_thinking) < len(last_thinking):
                yield "\n--- ai-thinking-reset ---\n"
                last_thinking = ""

            if current_thinking != last_thinking:
                if not last_thinking:
                    yield "[thinking]\n"
                delta = current_thinking[len(last_thinking):]
                if delta:
                    yield delta
                last_thinking = current_thinking

            current_output = state.ai_output or ""
            if len(current_output) < len(last_output):
                yield "\n--- ai-output-reset ---\n"
                last_output = ""

            if current_output != last_output:
                if not last_output:
                    yield "\n[output]\n"
                delta = current_output[len(last_output):]
                if delta:
                    yield delta
                last_output = current_output

            if state.status in {"completed", "failed", "cancelled"} and not state.ai_output:
                yield f"\n--- run-status={state.status} ---\n"
                break

            await asyncio.sleep(0.25)

    return StreamingResponse(ai_stream(), media_type="text/plain; charset=utf-8")


@app.get("/runs/{run_id}", response_model=RunSummary)
async def get_run(run_id: str) -> RunSummary:
    manager: RunManager = app.state.run_manager
    return manager.get_run(run_id)


@app.get("/runs/{run_id}/logs", response_model=RunLogResponse)
async def get_run_logs(run_id: str) -> RunLogResponse:
    manager: RunManager = app.state.run_manager
    return manager.get_run_logs(run_id)
