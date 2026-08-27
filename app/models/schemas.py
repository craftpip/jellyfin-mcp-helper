from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

OperationMode = Literal["organize", "normalize"]
ItemKind = Literal["movie", "series", "skip", "extra"]
ScanStatus = Literal["running", "completed", "confirmed", "failed", "cancelled"]


class ScanRequest(BaseModel):
    replace_existing: bool = Field(default=True, alias="replaceExisting")
    operation: OperationMode = Field(default="organize")
    full_rescan: bool = Field(default=False, alias="fullRescan")

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
    show_folder_exists: bool = Field(default=False, alias="showFolderExists")
    season_folder_exists: bool = Field(default=False, alias="seasonFolderExists")
    file_exists: bool = Field(default=False, alias="fileExists")
    file_size: int | None = Field(default=None, alias="fileSize")
    cross_drive: bool = Field(default=False, alias="crossDrive")
    suspect: bool = False
    flags: list[str] = Field(default_factory=list)
    corrected: bool = False
    correction_note: str | None = None
    candidate_targets: list[CandidateTarget] = Field(default_factory=list, alias="candidateTargets")
    container_path: str | None = Field(default=None, alias="containerPath")
    source_folder: str | None = Field(default=None, alias="sourceFolder")
    extra_type: str | None = Field(default=None, alias="extraType")

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
    confirm_status: Literal["idle", "running", "completed", "failed"] = "idle"
    confirm_phase: Literal[
        "idle",
        "preparing",
        "moving",
        "deleting_source",
        "triggering_jellyfin",
        "completed",
        "failed",
    ] = "idle"
    confirm_current_item: str | None = None
    confirm_current_target: str | None = None
    confirm_started_at: datetime | None = None
    confirm_total: int = 0
    confirm_processed: int = 0
    confirm_start_moved: int = 0
    confirm_start_replaced: int = 0
    confirm_start_failed: int = 0
    confirm_current_size_bytes: int | None = None
    confirm_current_copied_bytes: int | None = None
    confirm_current_speed_bytes: float | None = None
    confirm_current_percent: float | None = None
    confirm_cross_drive: bool | None = None
    confirm_note: str | None = None
    confirm_last_update_at: datetime | None = None
    confirm_queue_length: int = 0
    confirm_queue_items: int = 0


class ScanLogEntry(BaseModel):
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
    extra_type: str | None = None

    model_config = {"populate_by_name": True}


class CandidateTarget(BaseModel):
    path: str
    label: str
    evidence: str
    source: str = "folder"
    reclassify_as_movie: bool = False


class ResolvedTarget(BaseModel):
    root_key: str
    target_dir: str
    target_path: str
    created_show_folder: bool = False
    created_movie_folder: bool = False
    existing_match: str | None = None
    show_folder_exists: bool = False
    season_folder_exists: bool = False
    phantom_show_folder: bool = False
    has_previous_season: bool = False
    max_existing_season: int | None = None
    has_previous_episode: bool = False
    series_key: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    candidate_targets: list[CandidateTarget] = Field(default_factory=list)


class CandidateItem(BaseModel):
    source_root_key: str
    source_root: str
    source_path: str
    name: str
    extension: str | None = None
    container_path: str | None = None
    relative_path: str | None = None
    file_size: int | None = None
    in_progress: bool = False
