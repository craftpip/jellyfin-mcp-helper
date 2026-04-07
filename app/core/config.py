from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"


class Settings(BaseSettings):
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    
    # Integration toggles
    enable_download_client_check: bool = Field(default=True, alias="ENABLE_DOWNLOAD_CLIENT_CHECK")
    enable_jellyfin_integration: bool = Field(default=True, alias="ENABLE_JELLYFIN_INTEGRATION")
    
    # Download client settings (qBittorrent, etc.)
    download_client: str = Field(default="", alias="DOWNLOAD_CLIENT")
    qbt_mcp_url: str | None = Field(default=None, alias="QBT_MCP_URL")
    qbt_mcp_api_key: str | None = Field(default=None, alias="QBT_MCP_API_KEY")
    
    # Jellyfin settings
    jellyfin_base_url: str | None = Field(default=None, alias="JELLYFIN_BASE_URL")
    jellyfin_api_key: str | None = Field(default=None, alias="JELLYFIN_API_KEY")
    jellyfin_movie_library_name: str = Field(default="Movies", alias="JELLYFIN_MOVIE_LIBRARY_NAME")
    jellyfin_series_library_name: str = Field(default="Shows", alias="JELLYFIN_SERIES_LIBRARY_NAME")

    # Model settings
    model_provider: str = Field(default="ollama", alias="MODEL_PROVIDER")
    model_mode: str = Field(default="external-classifier", alias="MODEL_MODE")
    model_base_url: str | None = Field(default=None, alias="MODEL_BASE_URL")
    model_name: str = Field(default="llama3.2:1b", alias="MODEL_NAME")
    model_temperature: float = Field(default=0.0, alias="MODEL_TEMPERATURE")
    model_classify_confidence_threshold: float = Field(default=0.65, alias="MODEL_CLASSIFY_CONFIDENCE_THRESHOLD")
    model_path_confidence_threshold: float = Field(default=0.6, alias="MODEL_PATH_CONFIDENCE_THRESHOLD")
    model_request_timeout_seconds: float = Field(default=120.0, alias="MODEL_REQUEST_TIMEOUT_SECONDS")
    model_retry_attempts: int = Field(default=2, alias="MODEL_RETRY_ATTEMPTS")

    # Paths settings
    download_roots: str = Field(default="", alias="DOWNLOAD_ROOTS")
    movie_roots: str = Field(default="", alias="MOVIE_ROOTS")
    series_roots: str = Field(default="", alias="SERIES_ROOTS")

    model_config = {
        "populate_by_name": True,
        "env_file": ".env",
        "extra": "ignore",
    }


class PathsConfig(BaseModel):
    download_roots: list[str] = Field(default_factory=list, alias="downloadRoots")
    movie_roots: dict[str, str] = Field(default_factory=dict, alias="movieRoots")
    series_roots: dict[str, str] = Field(default_factory=dict, alias="seriesRoots")
    library_layout: dict[str, str] = Field(
        default_factory=lambda: {
            "movieFolderStyle": "Movie Title (Year)",
            "seasonFolderStyle": "Season 01",
            "episodeFileStyle": "Show Name - S01E01",
        },
        alias="libraryLayout",
    )

    model_config = {"populate_by_name": True}

    def get_media_prefixes(self) -> list[str]:
        """Extract media prefixes from download_roots.
        
        Example: ['/media1/torrents', '/media2/torrents'] -> ['/media1', '/media2']
        """
        prefixes = []
        for root in self.download_roots:
            # Remove trailing /torrents or similar suffix to get media prefix
            path_obj = Path(root)
            # Get parent if it ends with 'torrents', else use the last component
            if path_obj.name in ("torrents", "downloads"):
                prefix = str(path_obj.parent)
            else:
                # If no standard suffix, use as-is
                prefix = root
            if prefix not in prefixes:
                prefixes.append(prefix)
        return prefixes

    def find_download_root_for_folder(self, folder_name: str) -> str | None:
        """Find which download root contains the given folder.
        
        Args:
            folder_name: Name of the folder to search for
            
        Returns:
            The download root path that contains this folder, or None
        """
        for root in self.download_roots:
            folder_path = Path(root) / folder_name
            if folder_path.exists():
                return root
        return None

    @classmethod
    def from_env(cls, settings: Settings) -> "PathsConfig":
        download_roots = [p.strip() for p in settings.download_roots.split(",") if p.strip()]
        movie_roots_list = [p.strip() for p in settings.movie_roots.split(",") if p.strip()]
        series_roots_list = [p.strip() for p in settings.series_roots.split(",") if p.strip()]

        movie_roots: dict[str, str] = {}
        series_roots: dict[str, str] = {}

        for i, path in enumerate(movie_roots_list):
            movie_roots[f"movie_{i}"] = path

        for i, path in enumerate(series_roots_list):
            series_roots[f"series_{i}"] = path

        return cls(
            download_roots=download_roots,
            movie_roots=movie_roots,
            series_roots=series_roots,
        )


class PromptPolicy(BaseModel):
    classify_as: list[str] = Field(default_factory=lambda: ["movie", "series", "skip"], alias="classifyAs")
    extract_fields: list[str] = Field(
        default_factory=lambda: ["title", "year", "season", "episode", "confidence", "reason"],
        alias="extractFields",
    )

    model_config = {"populate_by_name": True}


class ModelConfig(BaseModel):
    provider: str = "ollama"
    mode: str = "external-classifier"
    base_url: str | None = None
    model: str = "llama3.2:1b"
    temperature: float = 0.0
    prompt_policy: PromptPolicy = Field(default_factory=PromptPolicy)
    classify_confidence_threshold: float = 0.65
    path_confidence_threshold: float = 0.6
    request_timeout_seconds: float = 120.0
    retry_attempts: int = 2

    model_config = {"populate_by_name": True}

    @classmethod
    def from_env(cls, settings: Settings) -> "ModelConfig":
        return cls(
            provider=settings.model_provider,
            mode=settings.model_mode,
            base_url=settings.model_base_url,
            model=settings.model_name,
            temperature=settings.model_temperature,
            classify_confidence_threshold=settings.model_classify_confidence_threshold,
            path_confidence_threshold=settings.model_path_confidence_threshold,
            request_timeout_seconds=settings.model_request_timeout_seconds,
            retry_attempts=settings.model_retry_attempts,
        )


class AppConfig(BaseModel):
    paths: PathsConfig
    model: ModelConfig
    log_dir: Path
    report_dir: Path


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    return AppConfig(
        paths=PathsConfig.from_env(settings),
        model=ModelConfig.from_env(settings),
        log_dir=LOG_DIR,
        report_dir=REPORT_DIR,
    )
