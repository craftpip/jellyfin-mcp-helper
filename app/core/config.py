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

    # Classification / path-resolution confidence thresholds
    model_classify_confidence_threshold: float = Field(default=0.65, alias="MODEL_CLASSIFY_CONFIDENCE_THRESHOLD")
    model_path_confidence_threshold: float = Field(default=0.6, alias="MODEL_PATH_CONFIDENCE_THRESHOLD")

    # Web UI settings. The UI is mounted at / on the MCP app, so it shares the
    # single MCP port. WEB_UI_PORT is deprecated/unused (kept for compat).
    web_ui_enabled: bool = Field(default=False, alias="WEB_UI_ENABLED")
    web_ui_port: int = Field(default=18329, alias="WEB_UI_PORT")

    # Web UI panel auth. Empty (default) = direct login, no password prompt.
    ui_panel_password: str = Field(default="", alias="UI_PANEL_PASSWORD")

    # MCP access control. When true (default), all unauthenticated MCP requests
    # pass through. When false, /mcp requests must present a valid API key from
    # MCP_KEYS_FILE (or ADMIN_UI_TOKEN).
    mcp_allow_unauthenticated: bool = Field(default=True, alias="MCP_ALLOW_UNAUTHENTICATED")
    # Path to the JSON file holding hashed API keys for MCP access.
    mcp_keys_file: str = Field(default="config/mcp_keys.json", alias="MCP_KEYS_FILE")
    # Optional master token accepted as a valid MCP key for the "admin" user.
    admin_ui_token: str | None = Field(default=None, alias="ADMIN_UI_TOKEN")

    # Paths settings
    download_roots: str = Field(default="", alias="DOWNLOAD_ROOTS")
    movie_roots: str = Field(default="", alias="MOVIE_ROOTS")
    series_roots: str = Field(default="", alias="SERIES_ROOTS")

    # Series title aliases: "alias::canonical" entries separated by commas.
    # Maps release titles (often Japanese) to the library folder name.
    series_title_aliases: str = Field(default="", alias="SERIES_TITLE_ALIASES")

    model_config = {
        "populate_by_name": True,
        "env_file": ".env",
        "extra": "ignore",
    }


class PathsConfig(BaseModel):
    download_roots: list[str] = Field(default_factory=list, alias="downloadRoots")
    movie_roots: dict[str, str] = Field(default_factory=dict, alias="movieRoots")
    movie_root_descriptions: dict[str, str] = Field(default_factory=dict, alias="movieRootDescriptions")
    series_roots: dict[str, str] = Field(default_factory=dict, alias="seriesRoots")
    series_root_descriptions: dict[str, str] = Field(default_factory=dict, alias="seriesRootDescriptions")
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
        
        Example: ['/data/torrents', '/data2/torrents'] -> ['/data', '/data2']
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
        movie_root_descriptions: dict[str, str] = {}
        series_roots: dict[str, str] = {}
        series_root_descriptions: dict[str, str] = {}

        for i, entry in enumerate(movie_roots_list):
            parts = entry.split("::", 1)
            path = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else f"Movies folder {i + 1}"
            movie_roots[f"movie_{i}"] = path
            movie_root_descriptions[f"movie_{i}"] = description

        for i, entry in enumerate(series_roots_list):
            parts = entry.split("::", 1)
            path = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else f"Series folder {i + 1}"
            series_roots[f"series_{i}"] = path
            series_root_descriptions[f"series_{i}"] = description

        return cls(
            download_roots=download_roots,
            movie_roots=movie_roots,
            movie_root_descriptions=movie_root_descriptions,
            series_roots=series_roots,
            series_root_descriptions=series_root_descriptions,
        )


class ModelConfig(BaseModel):
    classify_confidence_threshold: float = 0.65
    path_confidence_threshold: float = 0.6

    model_config = {"populate_by_name": True}

    @classmethod
    def from_env(cls, settings: Settings) -> "ModelConfig":
        return cls(
            classify_confidence_threshold=settings.model_classify_confidence_threshold,
            path_confidence_threshold=settings.model_path_confidence_threshold,
        )


class AppConfig(BaseModel):
    paths: PathsConfig
    model: ModelConfig
    series_title_aliases: dict[str, str] = Field(default_factory=dict)
    log_dir: Path
    report_dir: Path


def _parse_series_title_aliases(raw: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "::" not in entry:
            continue
        alias, canonical = (part.strip() for part in entry.split("::", 1))
        if alias and canonical:
            aliases[alias] = canonical
    return aliases


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings/config so the next read re-parses .env.

    Called by the env manager after live-applied variables are written to
    os.environ, so per-request consumers (auth, JellyfinClient, model clients)
    pick up the new values without a restart.
    """
    global _settings
    _settings = None
    get_config.cache_clear()


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    return AppConfig(
        paths=PathsConfig.from_env(settings),
        model=ModelConfig.from_env(settings),
        series_title_aliases=_parse_series_title_aliases(settings.series_title_aliases),
        log_dir=LOG_DIR,
        report_dir=REPORT_DIR,
    )
