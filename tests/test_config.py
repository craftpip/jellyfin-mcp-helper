from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import (
    AppConfig,
    ModelConfig,
    PathsConfig,
    Settings,
    _parse_series_title_aliases,
    get_config,
    get_settings,
    reset_settings,
)


# ---------------------------------------------------------------------------
# _parse_series_title_aliases
# ---------------------------------------------------------------------------

class TestParseSeriesTitleAliases:
    def test_basic_alias(self) -> None:
        result = _parse_series_title_aliases("Alias::Canonical")
        assert result == {"Alias": "Canonical"}

    def test_multiple_aliases(self) -> None:
        result = _parse_series_title_aliases("A::B, C::D, E::F")
        assert result == {"A": "B", "C": "D", "E": "F"}

    def test_empty_string(self) -> None:
        assert _parse_series_title_aliases("") == {}

    def test_skips_entries_without_separator(self) -> None:
        result = _parse_series_title_aliases("NoSeparator, AlsoNo::Here")
        assert len(result) == 1

    def test_strips_whitespace(self) -> None:
        result = _parse_series_title_aliases("  Alias  ::  Canonical  ")
        assert result == {"Alias": "Canonical"}

    def test_skips_empty_alias(self) -> None:
        result = _parse_series_title_aliases("::Canonical")
        assert result == {}

    def test_skips_empty_canonical(self) -> None:
        result = _parse_series_title_aliases("Alias::")
        assert result == {}


# ---------------------------------------------------------------------------
# PathsConfig
# ---------------------------------------------------------------------------

class TestPathsConfig:
    def test_get_media_prefixes_with_torrents_suffix(self) -> None:
        config = PathsConfig(downloadRoots=["/data/torrents"])
        assert config.get_media_prefixes() == ["/data"]

    def test_get_media_prefixes_with_downloads_suffix(self) -> None:
        config = PathsConfig(downloadRoots=["/data/downloads"])
        assert config.get_media_prefixes() == ["/data"]

    def test_get_media_prefixes_without_standard_suffix(self) -> None:
        config = PathsConfig(downloadRoots=["/data/myfolder"])
        assert config.get_media_prefixes() == ["/data/myfolder"]

    def test_get_media_prefixes_deduplicates(self) -> None:
        config = PathsConfig(downloadRoots=["/data/torrents", "/data/more_torrents"])
        prefixes = config.get_media_prefixes()
        assert len(prefixes) == 2

    def test_get_media_prefixes_empty(self) -> None:
        config = PathsConfig(downloadRoots=[])
        assert config.get_media_prefixes() == []

    def test_find_download_root_for_folder_exists(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        (root / "My Show").mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        result = config.find_download_root_for_folder("My Show")
        assert result == str(root)

    def test_find_download_root_for_folder_not_exists(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        result = config.find_download_root_for_folder("Nonexistent")
        assert result is None

    def test_find_download_root_for_folder_multiple_roots(self, tmp_path: Path) -> None:
        root1 = tmp_path / "torrents1"
        root2 = tmp_path / "torrents2"
        root1.mkdir()
        root2.mkdir()
        (root2 / "Show").mkdir()
        config = PathsConfig(downloadRoots=[str(root1), str(root2)])
        result = config.find_download_root_for_folder("Show")
        assert result == str(root2)

    def test_from_env_parses_download_roots(self) -> None:
        settings = Settings(
            DOWNLOAD_ROOTS="/data/torrents,/data2/torrents",
            MOVIE_ROOTS="",
            SERIES_ROOTS="",
        )
        config = PathsConfig.from_env(settings)
        assert config.download_roots == ["/data/torrents", "/data2/torrents"]

    def test_from_env_parses_movie_roots_with_descriptions(self) -> None:
        settings = Settings(
            DOWNLOAD_ROOTS="",
            MOVIE_ROOTS="/movies1::Film library,/movies2",
            SERIES_ROOTS="",
        )
        config = PathsConfig.from_env(settings)
        assert config.movie_roots["movie_0"] == "/movies1"
        assert config.movie_root_descriptions["movie_0"] == "Film library"
        assert config.movie_roots["movie_1"] == "/movies2"
        assert config.movie_root_descriptions["movie_1"] == "Movies folder 2"

    def test_from_env_parses_series_roots_with_descriptions(self) -> None:
        settings = Settings(
            DOWNLOAD_ROOTS="",
            MOVIE_ROOTS="",
            SERIES_ROOTS="/shows::TV library",
        )
        config = PathsConfig.from_env(settings)
        assert config.series_roots["series_0"] == "/shows"
        assert config.series_root_descriptions["series_0"] == "TV library"

    def test_from_env_empty_roots(self) -> None:
        settings = Settings(
            DOWNLOAD_ROOTS="",
            MOVIE_ROOTS="",
            SERIES_ROOTS="",
        )
        config = PathsConfig.from_env(settings)
        assert config.download_roots == []
        assert config.movie_roots == {}
        assert config.series_roots == {}

    def test_default_library_layout(self) -> None:
        config = PathsConfig()
        assert config.library_layout["movieFolderStyle"] == "Movie Title (Year)"
        assert config.library_layout["seasonFolderStyle"] == "Season 01"
        assert config.library_layout["episodeFileStyle"] == "Show Name - S01E01"


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------

class TestModelConfig:
    def test_defaults(self) -> None:
        config = ModelConfig()
        assert config.classify_confidence_threshold == 0.65
        assert config.path_confidence_threshold == 0.6

    def test_from_env(self) -> None:
        settings = Settings(
            MODEL_CLASSIFY_CONFIDENCE_THRESHOLD=0.8,
            MODEL_PATH_CONFIDENCE_THRESHOLD=0.7,
        )
        config = ModelConfig.from_env(settings)
        assert config.classify_confidence_threshold == 0.8
        assert config.path_confidence_threshold == 0.7


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    def test_settings_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_UI_ENABLED", "true")
        monkeypatch.setenv("UI_PANEL_PASSWORD", "secret")
        settings = Settings()
        assert settings.web_ui_enabled is True
        assert settings.ui_panel_password == "secret"

    def test_settings_type_annotations(self) -> None:
        fields = Settings.model_fields
        assert "enable_download_client_check" in fields
        assert "web_ui_enabled" in fields
        assert "mcp_allow_unauthenticated" in fields
        assert "ui_panel_password" in fields

    def test_settings_env_prefix_mappings(self) -> None:
        fields = Settings.model_fields
        assert fields["enable_download_client_check"].alias == "ENABLE_DOWNLOAD_CLIENT_CHECK"
        assert fields["web_ui_enabled"].alias == "WEB_UI_ENABLED"
        assert fields["download_roots"].alias == "DOWNLOAD_ROOTS"

    def test_settings_extra_fields_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TOTALLY_UNKNOWN_FIELD", "value")
        settings = Settings()
        assert hasattr(settings, "enable_download_client_check")


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------

class TestAppConfig:
    def test_construction(self, tmp_path: Path) -> None:
        config = AppConfig(
            paths=PathsConfig(),
            model=ModelConfig(),
            series_title_aliases={"Alias": "Canonical"},
            log_dir=tmp_path / "logs",
            report_dir=tmp_path / "reports",
        )
        assert config.series_title_aliases == {"Alias": "Canonical"}

    def test_default_aliases_empty(self) -> None:
        config = AppConfig(
            paths=PathsConfig(),
            model=ModelConfig(),
            log_dir=Path("/tmp/logs"),
            report_dir=Path("/tmp/reports"),
        )
        assert config.series_title_aliases == {}


# ---------------------------------------------------------------------------
# get_config / get_settings / reset_settings
# ---------------------------------------------------------------------------

class TestGlobalConfig:
    def test_get_settings_returns_settings(self) -> None:
        reset_settings()
        try:
            settings = get_settings()
            assert isinstance(settings, Settings)
        finally:
            reset_settings()

    def test_reset_settings_clears_cache(self) -> None:
        reset_settings()
        try:
            s1 = get_settings()
            s2 = get_settings()
            assert s1 is s2
            reset_settings()
            s3 = get_settings()
            assert s1 is not s3
        finally:
            reset_settings()
