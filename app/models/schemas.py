from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


OperationMode = Literal["organize", "normalize"]
NormalizeMode = Literal["safe", "full"]
ItemKind = Literal["movie", "series", "skip"]
ScanStatus = Literal["running", "completed", "confirmed", "failed"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ScanRequest(BaseModel):
    replace_existing: bool = Field(default=True, alias="replaceExisting")
    operation: OperationMode = Field(default="organize")
    allow_medium: bool = Field(default=False, alias="allowMedium")
    use_local_ai: bool = Field(default=False, alias="useLocalAI")

    model_config = {"populate_by_name": True}


class ScannedItem(BaseModel):
    confirm_id: str = Field(alias="confirmId")
    source_path: str = Field(alias="sourcePath")
    name: str
    item_type: ItemKind
    confidence: float
    reason: str
    target_path: str
    action: Literal["move", "replace", "skip"]
    error: str | None = None
    confirmed: bool = False
    folder_exists: bool = Field(default=False, alias="folderExists")

    model_config = {"populate_by_name": True}


class ScanCounts(BaseModel):
    total: int = 0
    movies: int = 0
    series: int = 0
    skipped: int = 0
    moved: int = 0
    replaced: int = 0
    failed: int = 0


class ScanPlan(BaseModel):
    scan_id: str
    status: ScanStatus
    operation: OperationMode
    items: list[ScannedItem] = Field(default_factory=list)
    counts: ScanCounts = Field(default_factory=ScanCounts)
    skipped_in_progress: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_candidates: int = 0
    processed_candidates: int = 0
    current_candidate: str | None = None
    current_candidate_index: int = 0
    confirmed_at: datetime | None = None
    error: str | None = None
    service_errors: dict[str, str] = Field(default_factory=dict)


class ScanLogEntry(BaseModel):
    timestamp: datetime
    level: Literal["info", "warning", "error"]
    event: str
    message: str
    item_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# Legacy models - kept for backward compatibility
class RunRequest(BaseModel):
    dry_run: bool = Field(default=True, alias="dryRun")
    replace_existing: bool = Field(default=True, alias="replaceExisting")
    operation: OperationMode = Field(default="organize")
    normalize_mode: NormalizeMode = Field(default="safe", alias="normalizeMode")
    allow_medium: bool = Field(default=False, alias="allowMedium")
    use_local_ai: bool = Field(default=False, alias="useLocalAI")

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
    episode_title: str | None = None
    series_alias: str | None = None
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
    folder_exists: bool = False


class CandidateItem(BaseModel):
    source_root_key: str
    source_root: str
    source_path: str
    name: str
    extension: str | None = None
    container_path: str | None = None
    relative_path: str | None = None
    file_size: int | None = None


class RunState(BaseModel):
    run_id: str
    status: RunStatus
    dry_run: bool
    replace_existing: bool
    operation: OperationMode
    normalize_mode: NormalizeMode
    allow_medium: bool
    use_local_ai: bool
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
