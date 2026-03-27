from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"


class PathsConfig(BaseModel):
    torrent_roots: list[str] = Field(alias="torrentRoots")
    movie_roots: dict[str, str] = Field(alias="movieRoots")
    series_roots: dict[str, str] = Field(alias="seriesRoots")
    library_layout: dict[str, str] = Field(alias="libraryLayout")

    model_config = {"populate_by_name": True}


class PromptPolicy(BaseModel):
    classify_as: list[str] = Field(alias="classifyAs")
    extract_fields: list[str] = Field(alias="extractFields")

    model_config = {"populate_by_name": True}


class ModelConfig(BaseModel):
    provider: str
    mode: str
    base_url: str = Field(alias="baseUrl")
    model: str
    temperature: float = 0.0
    prompt_policy: PromptPolicy = Field(alias="promptPolicy")
    classify_confidence_threshold: float = Field(default=0.65, alias="classifyConfidenceThreshold")
    path_confidence_threshold: float = Field(default=0.6, alias="pathConfidenceThreshold")
    request_timeout_seconds: float = Field(default=120.0, alias="requestTimeoutSeconds")
    retry_attempts: int = Field(default=2, alias="retryAttempts")

    model_config = {"populate_by_name": True}


class AppConfig(BaseModel):
    paths: PathsConfig
    model: ModelConfig
    log_dir: Path
    report_dir: Path


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        paths=PathsConfig.model_validate(_load_json(CONFIG_DIR / "paths.json")),
        model=ModelConfig.model_validate(_load_json(CONFIG_DIR / "model.json")),
        log_dir=LOG_DIR,
        report_dir=REPORT_DIR,
    )
