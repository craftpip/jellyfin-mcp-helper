from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import AppConfig
from app.models.schemas import RunLogResponse, RunRequest, RunState, RunSummary
from app.services.normalizer import NormalizerService
from app.services.organizer import OrganizerService


class RunManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._runs: dict[str, RunState] = {}
        self._current_run_id: str | None = None
        self._organizer = OrganizerService(config)
        self._normalizer = NormalizerService(config)

    async def start_run(self, request: RunRequest) -> RunSummary:
        async with self._lock:
            active = self.get_current_run_state()
            if active and active.status in {"queued", "running"}:
                raise HTTPException(status_code=409, detail="A run is already active")

            now = datetime.now(UTC)
            run_id = uuid4().hex
            log_path = self._config.log_dir / f"run-{run_id}.jsonl"
            summary_path = self._config.report_dir / f"run-{run_id}.json"
            state = RunState(
                run_id=run_id,
                status="queued",
                dry_run=request.dry_run,
                replace_existing=request.replace_existing,
                operation=request.operation,
                normalize_mode=request.normalize_mode,
                allow_medium=request.allow_medium,
                use_local_ai=request.use_local_ai,
                started_at=now,
                updated_at=now,
                logs=[],
                active_step="queued",
                active_item_path=None,
                ai_thinking="",
                ai_output="",
                log_path=str(log_path),
                summary_path=str(summary_path),
            )
            self._runs[run_id] = state
            self._current_run_id = run_id
            asyncio.create_task(self._execute_run(run_id))
            return self._summary_for(state)

    def get_current_run(self) -> RunSummary | None:
        state = self.get_current_run_state()
        if not state:
            return None
        return self._summary_for(state)

    def get_run(self, run_id: str) -> RunSummary:
        state = self._runs.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="Run not found")
        return self._summary_for(state)

    def get_run_logs(self, run_id: str) -> RunLogResponse:
        state = self._runs.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="Run not found")
        return RunLogResponse(run_id=run_id, status=state.status, logs=state.logs)

    def get_current_run_logs(self) -> RunLogResponse | None:
        state = self.get_current_run_state()
        if not state:
            return None
        return RunLogResponse(run_id=state.run_id, status=state.status, logs=state.logs)

    def get_current_run_state(self) -> RunState | None:
        if not self._current_run_id:
            return None
        return self._runs.get(self._current_run_id)

    async def _execute_run(self, run_id: str) -> None:
        state = self._runs[run_id]
        try:
            state.status = "running"
            state.updated_at = datetime.now(UTC)
            if state.operation == "normalize":
                self._normalizer.bind_run_state(state)
                await self._normalizer.execute(state)
            else:
                self._organizer.bind_run_state(state)
                self._organizer._resolver.bind_run_state(state)
                await self._organizer.execute(state)
            state.status = "completed"
        except Exception as exc:  # noqa: BLE001
            state.status = "failed"
            state.error = str(exc)
        finally:
            state.finished_at = datetime.now(UTC)
            state.updated_at = state.finished_at
            self._write_summary(state)

    def _write_summary(self, state: RunState) -> None:
        if not state.summary_path:
            return
        payload = self._summary_for(state).model_dump(mode="json")
        with Path(state.summary_path).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    @staticmethod
    def _summary_for(state: RunState) -> RunSummary:
        return RunSummary(
            run_id=state.run_id,
            status=state.status,
            dry_run=state.dry_run,
            replace_existing=state.replace_existing,
            operation=state.operation,
            normalize_mode=state.normalize_mode,
            allow_medium=state.allow_medium,
            use_local_ai=state.use_local_ai,
            started_at=state.started_at,
            updated_at=state.updated_at,
            finished_at=state.finished_at,
            counts=state.counts,
            active_step=state.active_step,
            active_item_path=state.active_item_path,
            ai_thinking=state.ai_thinking,
            ai_output=state.ai_output,
            logs=state.logs,
            summary_path=state.summary_path,
            log_path=state.log_path,
            error=state.error,
        )
