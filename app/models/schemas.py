from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ItemKind = Literal["movie", "series", "skip"]


class RunRequest(BaseModel):
    dry_run: bool = Field(default=True, alias="dryRun")
    replace_existing: bool = Field(default=True, alias="replaceExisting")

    model_config = {"populate_by_name": True}


class ProgressCounts(BaseModel):
    scanned: int = 0
    classified: int = 0
    moved: int = 0
    replaced: int = 0
    skipped: int = 0
    failed: int = 0


class RunLogEntry(BaseModel):
    timestamp: datetime
    level: Literal["info", "warning", "error"]
    event: str
    message: str
    item_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    kind: ItemKind = Field(alias="type")
    title: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    confidence: float = 0.0
    reason: str = ""

    model_config = {"populate_by_name": True}


class ResolvedTarget(BaseModel):
    root_key: str
    target_dir: str
    target_path: str
    created_show_folder: bool = False
    created_movie_folder: bool = False
    existing_match: str | None = None


class CandidateItem(BaseModel):
    source_root_key: str
    source_root: str
    source_path: str
    name: str
    extension: str | None = None
    container_path: str | None = None
    relative_path: str | None = None


class RunState(BaseModel):
    run_id: str
    status: RunStatus
    dry_run: bool
    replace_existing: bool
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    counts: ProgressCounts = Field(default_factory=ProgressCounts)
    logs: list[RunLogEntry] = Field(default_factory=list)
    active_step: str | None = None
    active_item_path: str | None = None
    ai_thinking: str = ""
    ai_output: str = ""
    summary_path: str | None = None
    log_path: str | None = None
    error: str | None = None


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    dry_run: bool
    replace_existing: bool
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    counts: ProgressCounts
    active_step: str | None = None
    active_item_path: str | None = None
    ai_thinking: str = ""
    ai_output: str = ""
    logs: list[RunLogEntry] = Field(default_factory=list)
    summary_path: str | None = None
    log_path: str | None = None
    error: str | None = None


class RunLogResponse(BaseModel):
    run_id: str
    status: RunStatus
    logs: list[RunLogEntry]
