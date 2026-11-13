from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"
DOTENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    # Integration toggles
    enable_jellyfin_integration: bool = Field(default=True, alias="ENABLE_JELLYFIN_INTEGRATION")

    # Download settings — in-progress download detection via incomplete-file markers
    enable_incomplete_download_detection: bool = Field(default=True, alias="ENABLE_INCOMPLETE_DOWNLOAD_DETECTION")

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

    # Panel link for the 'jellysort_panel_link' MCP tool. The container cannot
    # see the host's LAN IP or published port, so the tool prefers this
    # explicit URL, then the MCP request's Host header, then the
    # JELLYFIN_BASE_URL host + PANEL_PORT as a best guess.
    panel_public_url: str = Field(default="", alias="PANEL_PUBLIC_URL")
    panel_port: int = Field(default=18328, alias="PANEL_PORT")

    # Web UI panel auth. Empty (default) = direct login, no password prompt.
    ui_panel_password: str = Field(default="", alias="UI_PANEL_PASSWORD")

    # MCP access control. Single token: when JELLYSORT_MCP_TOKEN is set, every
    # /mcp request must present it as Bearer/X-API-Key; when empty, MCP is open.
    # MCP_DEFAULT_TOKEN is kept as deprecated alias for existing .env files.
    jellysort_mcp_token: str | None = Field(default=None, alias="JELLYSORT_MCP_TOKEN")
    mcp_default_token: str | None = Field(default=None, alias="MCP_DEFAULT_TOKEN")
    # Deprecated alias for backward compat
    admin_ui_token: str | None = Field(default=None, alias="ADMIN_UI_TOKEN")

    @property
    def mcp_token(self) -> str | None:
        """Effective MCP token — prefers JELLYSORT_MCP_TOKEN, falls back to deprecated MCP_DEFAULT_TOKEN/ADMIN_UI_TOKEN."""
        return self.jellysort_mcp_token or self.mcp_default_token or self.admin_ui_token

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

_DOTENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _read_dotenv(path: Path | None = None) -> dict[str, str]:
    """Parse KEY=value lines from the .env file (comments/blanks skipped)."""
    env_path = path or DOTENV_PATH
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _DOTENV_LINE_RE.match(line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        result[key] = value
    return result


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        # The .env file is authoritative: parsed entries are fed as init
        # kwargs (highest pydantic precedence), so it wins over inherited
        # process env without anyone patching os.environ.
        _settings = Settings(**_read_dotenv())
    return _settings


def reset_settings() -> None:
    """Drop the cached settings so the next read re-parses .env.

    Called by the env manager after .env is rewritten, so per-request
    consumers (auth, JellyfinClient, model clients) pick up the new values
    without a restart. No os.environ mutation involved.
    """
    global _settings
    _settings = None


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
