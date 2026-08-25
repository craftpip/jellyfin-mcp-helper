from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

from app.core.config import AppConfig
from app.core.constants import VIDEO_EXTENSIONS
from app.models.schemas import CandidateItem, CandidateTarget, ClassificationResult, ResolvedTarget
from app.services.classifier import (
    _candidate_has_movie_marker,
    _get_folder_title,
    _is_generic_extra_title,
    _is_generic_folder_title,
)
from app.services.scanner import list_target_paths

logger = logging.getLogger(__name__)

INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')
WORD_RE = re.compile(r"[a-z0-9]+")
MAX_AI_PATH_CHOICES = 20
MAX_CANDIDATE_TARGETS = 5
EPISODE_TAG_RE = re.compile(r"\bs\d{1,2}e\d{1,3}\b.*$", re.IGNORECASE)
TRAILING_YEAR_RE = re.compile(r"\s+\d{4}$")
POST_NUMBER_TITLE_RE = re.compile(r"\d{2,4}\s*[-–—:]\s*(.+)$", re.IGNORECASE)
ARC_FILLER_WORDS = {"the", "and", "of", "a", "an"}
_SEASON_ARC_MARKER_RE = re.compile(r"\b(?:s\d{1,2}|season\s*\d{1,2})\b\s*[-–—._]?\s*", re.IGNORECASE)


def _is_hidden(value: str) -> bool:
    return any(part.startswith(".") for part in value.split("/") if part)


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part)


def sanitize_name(value: str) -> str:
    cleaned = INVALID_PATH_CHARS.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Unknown"


def fold_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_text(value: str) -> str:
    value = value.replace("'", "")
    value = fold_diacritics(value)
    return " ".join(WORD_RE.findall(value.lower()))


def normalize_series_text(value: str) -> str:
    return TRAILING_YEAR_RE.sub("", normalize_text(value)).strip()


def tokenize(value: str) -> set[str]:
    return set(WORD_RE.findall(fold_diacritics(value).lower()))


def _normalize_arc_text(value: str) -> str:
    value = fold_diacritics(value).lower().replace("&", " and ")
    tokens = [t for t in WORD_RE.findall(value) if t not in ARC_FILLER_WORDS]
    return " ".join(tokens)


def season_arc_text(value: str) -> str:
    """Release-side season-arc text after the Sxx / Season xx marker.

    'Nimbus S21 Sun & Moon Ultra Adventures' -> 'sun moon ultra adventures'.
    """
    match = _SEASON_ARC_MARKER_RE.search(value)
    if not match:
        return ""
    return _normalize_arc_text(value[match.end():])


def season_dir_arc(season_dir_name: str) -> str:
    """Library-side season-arc text from a season dir name.

    's21 - Sun and Moon Ultra Adventures' -> 'sun moon ultra adventures'.
    """
    stripped = season_dir_name.strip()
    match = _SEASON_ARC_MARKER_RE.match(stripped)
    if not match:
        return _normalize_arc_text(stripped)
    return _normalize_arc_text(stripped[match.end():])


def series_lookup_key(title: str, year: int | None = None) -> str:
    normalized = normalize_series_text(title)
    if year is not None:
        return f"{normalized}::{year}"
    return normalized


@cache
def series_aliases(path: str) -> set[str]:
    root = Path(path)
    aliases = {root.name}
    if not root.exists() or not root.is_dir():
        return aliases

    logger.debug("Building aliases for %s", path)
    sample_count = 0
    for ext in VIDEO_EXTENSIONS:
        for file_path in root.rglob(f"*{ext}"):
            if _is_hidden_path(file_path):
                continue
            if sample_count >= 12:
                break
            cleaned = EPISODE_TAG_RE.sub("", file_path.stem).strip(" -._")
            if cleaned:
                aliases.add(cleaned)
            post_number = POST_NUMBER_TITLE_RE.search(cleaned)
            if post_number:
                ep_title = post_number.group(1).strip(" -._")
                if ep_title and ep_title != cleaned:
                    aliases.add(ep_title)
            sample_count += 1
        if sample_count >= 12:
            break
    logger.debug("Built %d aliases for %s (folder=%s)", len(aliases), path, root.name)
    return aliases


def season_dir_candidates(season_number: int) -> set[str]:
    return {
        f"season {season_number}",
        f"season {season_number:02d}",
        f"s{season_number}",
        f"s{season_number:02d}",
    }


@cache
def series_video_count(path: str) -> int:
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return 0
    count = 0
    for file_path in root.rglob("*"):
        if _is_hidden_path(file_path):
            continue
        if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
            count += 1
            if count >= 20:
                return count
    return count


def clear_resolver_cache() -> None:
    series_aliases.cache_clear()
    series_video_count.cache_clear()


class PathResolver:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._series_path_memory: dict[str, str] = {}
        self._series_alias_seasons: dict[tuple[str, str], int] = {}
        self._scan_prepared = False
        self._movie_existing_paths: list[str] = []
        self._series_existing_paths: list[str] = []

    def reset_runtime_state(self) -> None:
        self._series_path_memory.clear()
        self._series_alias_seasons.clear()
        self._scan_prepared = False
        self._movie_existing_paths = []
        self._series_existing_paths = []

    def prepare_scan(self, movie_roots: list[str], series_roots: list[str]) -> None:
        """List existing target folders once per scan instead of per candidate."""
        self._movie_existing_paths = []
        self._series_existing_paths = []
        for root in movie_roots:
            self._movie_existing_paths.extend(list_target_paths(root))
        for root in series_roots:
            self._series_existing_paths.extend(list_target_paths(root))
        self._scan_prepared = True
        logger.info(
            "[resolver] prepared scan index: %d movie folders, %d series folders",
            len(self._movie_existing_paths),
            len(self._series_existing_paths),
        )

    async def resolve(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        if classification.kind == "extra":
            return await self._resolve_extra(candidate, classification)
        if classification.kind == "movie":
            return await self._resolve_movie(candidate, classification)
        return await self._resolve_series(candidate, classification)

    async def _resolve_extra(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        # All extras go to a single "extras" folder under the show/movie, preserving relative path under extras/
        # Determine if it's a movie or series extra based on the classification's title/year and candidate
        # For simplicity, try to find the best matching show/movie folder, then use its extras subfolder
        # If we can't determine, fall back to the download root's extras
        is_series_extra = classification.season is not None or classification.episode is not None or "special" in (classification.extra_type or "") or "extra" in (classification.extra_type or "")
        # Try to resolve as series first if it looks like a series extra (has season/episode)
        if is_series_extra or classification.extra_type in ("special", "extra"):
            # Try series resolution but force extras subfolder
            # Level 1: main folder = show identity — never use file stem like ED/OP for lookup
            raw_title = classification.title or Path(candidate.container_path or candidate.source_path).name
            show_name = sanitize_name(raw_title)
            # Folder-first hierarchy: if title is generic extra (ED/OP/NC/SP), use folder-derived title
            if _is_generic_extra_title(show_name) or _is_generic_extra_title(raw_title) or _is_generic_folder_title(show_name):
                folder_title = _get_folder_title(candidate)
                if folder_title and not _is_generic_folder_title(folder_title) and not _is_generic_extra_title(folder_title):
                    show_name = sanitize_name(folder_title)
            # Find the best matching series folder
            all_series_paths = list(self._series_existing_paths)
            if not self._scan_prepared:
                for root in self._config.paths.series_roots.values():
                    all_series_paths.extend(list_target_paths(root))
            best_show = await self._pick_existing_path(
                media_kind="series",
                title=show_name,
                year=classification.year,
                target_paths=all_series_paths,
                desired_name=show_name,
            )
            if best_show:
                show_dir = Path(best_show)
            else:
                # Fallback to series root
                series_roots_list = list(self._config.paths.series_roots.values())
                index = int(candidate.source_root_key.split("_")[-1]) if "_" in candidate.source_root_key else 0
                series_root = self._pick_drive_root(candidate.source_path, series_roots_list, index)
                show_dir = Path(series_root) / show_name
            # extras folder under the show
            extras_dir = show_dir / "extras"
            # Preserve relative path under extras if the torrent had subfolders
            rel = Path(candidate.relative_path or candidate.name)
            # If the torrent is a folder of extras, keep its structure under extras/
            target_path = str(extras_dir / rel.name)
            # Also preserve subfolders if any
            if candidate.relative_path and "/" in candidate.relative_path:
                # Keep the relative path under extras
                target_path = str(extras_dir / Path(candidate.relative_path).name)
                # For nested extras folders, keep them
                if len(Path(candidate.relative_path).parts) > 1:
                    target_path = str(extras_dir / candidate.relative_path)
            return ResolvedTarget(
                root_key=candidate.source_root_key,
                target_dir=str(extras_dir),
                target_path=target_path,
                existing_match=best_show,
                show_folder_exists=show_dir.exists(),
                season_folder_exists=extras_dir.exists(),
                candidate_targets=[],
            )
        # Movie extra
        movie_roots_list = list(self._config.paths.movie_roots.values())
        index = int(candidate.source_root_key.split("_")[-1]) if "_" in candidate.source_root_key else 0
        movie_root = self._pick_drive_root(candidate.source_path, movie_roots_list, index)
        folder_name = self._movie_folder_name(classification)
        # Find best matching movie folder
        all_movie_paths = list(self._movie_existing_paths)
        if not self._scan_prepared:
            for root in movie_roots_list:
                all_movie_paths.extend(list_target_paths(root))
        best_movie = await self._pick_existing_path(
            media_kind="movie",
            title=classification.title or candidate.name,
            year=classification.year,
            target_paths=all_movie_paths,
            desired_name=folder_name,
        )
        movie_dir = Path(best_movie) if best_movie else Path(movie_root) / folder_name
        extras_dir = movie_dir / "extras"
        rel = Path(candidate.relative_path or candidate.name)
        target_path = str(extras_dir / rel.name)
        if candidate.relative_path and "/" in candidate.relative_path:
            target_path = str(extras_dir / candidate.relative_path)
        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(extras_dir),
            target_path=target_path,
            existing_match=best_movie,
            show_folder_exists=movie_dir.exists(),
            season_folder_exists=extras_dir.exists(),
            candidate_targets=[],
        )

    async def _resolve_movie(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        index = int(candidate.source_root_key.split("_")[-1]) if "_" in candidate.source_root_key else 0
        movie_roots_list = list(self._config.paths.movie_roots.values())
        movie_root = self._pick_drive_root(candidate.source_path, movie_roots_list, index)
        
        all_existing_paths = list(self._movie_existing_paths)
        if not self._scan_prepared:
            for root in movie_roots_list:
                all_existing_paths.extend(list_target_paths(root))
        folder_name = self._movie_folder_name(classification)
        best_match = await self._pick_existing_path(
            media_kind="movie",
            title=classification.title or candidate.name,
            year=classification.year,
            target_paths=all_existing_paths,
            desired_name=folder_name,
        )

        ext = Path(candidate.source_path).suffix or ".mkv"
        base_dir = Path(best_match) if best_match else Path(movie_root) / folder_name
        target_dir = base_dir if base_dir.is_dir() or not base_dir.suffix else base_dir.parent
        target_path = str(target_dir / f"{folder_name}{ext}")
        if best_match:
            logger.info("  [resolver] matched existing movie folder: %s", best_match)
        else:
            logger.info("  [resolver] new movie folder: %s", folder_name)
        candidates = self._build_movie_candidates(
            title=classification.title or candidate.name,
            year=classification.year,
            all_existing_paths=all_existing_paths,
            chosen_dir=target_dir,
            movie_root=movie_root,
            folder_name=folder_name,
        )
        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(target_dir),
            target_path=target_path,
            created_movie_folder=best_match is None,
            existing_match=best_match,
            show_folder_exists=best_match is not None,
            season_folder_exists=target_dir.exists(),
            candidate_targets=candidates,
        )

    @staticmethod
    def _pick_drive_root(source_path: str, roots: list[str], default_index: int) -> str:
        fallback = roots[default_index] if default_index < len(roots) else roots[0]
        try:
            source_dev = os.stat(source_path).st_dev
        except OSError:
            return fallback

        same_drive = []
        for root in roots:
            try:
                if os.stat(root).st_dev == source_dev:
                    same_drive.append(root)
            except OSError:
                continue

        if same_drive:
            if fallback in same_drive:
                return fallback
            return same_drive[0]

        return fallback

    async def _resolve_series(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        index = int(candidate.source_root_key.split("_")[-1]) if "_" in candidate.source_root_key else 0
        series_roots_list = list(self._config.paths.series_roots.values())
        series_root = self._pick_drive_root(candidate.source_path, series_roots_list, index)
        
        all_existing_paths = list(self._series_existing_paths)
        if not self._scan_prepared:
            for root in series_roots_list:
                all_existing_paths.extend(list_target_paths(root))
        raw_title = classification.title or candidate.name
        show_name = sanitize_name(raw_title)
        # Folder-first for series as well: generic file stem must not win over folder
        if _is_generic_extra_title(show_name) or _is_generic_extra_title(raw_title) or _is_generic_folder_title(show_name):
            folder_title = _get_folder_title(candidate)
            if folder_title and not _is_generic_folder_title(folder_title) and not _is_generic_extra_title(folder_title):
                show_name = sanitize_name(folder_title)
        show_name = re.sub(r"([^a-zA-Z0-9])\1+$", r"\1", show_name)
        series_key = series_lookup_key(show_name, classification.year)
        logger.info(
            "  [resolver] resolving series=%s season=%s episode=%s candidate=%s",
            show_name, classification.season, classification.episode, candidate.source_path,
        )
        logger.info("  [resolver] existing paths count: %d", len(all_existing_paths))
        if classification.series_alias:
            alias_season = self._lookup_series_alias_season(series_key, classification.series_alias)
            if alias_season:
                logger.info("  [resolver] alias \"%s\" → season %d (from memory)", classification.series_alias, alias_season)
        season_number = classification.season or self._lookup_series_alias_season(series_key, classification.series_alias) or 1
        if classification.series_alias and season_number != (classification.season or 1):
            logger.info("  [resolver] using season %d from alias \"%s\"", season_number, classification.series_alias)
        best_match = await self._pick_existing_path(
            media_kind="series",
            title=show_name,
            year=classification.year,
            target_paths=all_existing_paths,
            desired_name=show_name,
        )

        created_show_folder = False
        if best_match:
            show_dir = Path(best_match)
            logger.info("  [resolver] matched existing show folder: %s", best_match)
            self._remember_series_path(series_key, show_dir)
        else:
            remembered_path = self._lookup_series_path(series_key)
            if remembered_path:
                show_dir = Path(remembered_path)
                logger.info("  [resolver] reused show folder from memory: %s", remembered_path)
            else:
                show_dir = Path(series_root) / show_name
                logger.info("  [resolver] new show folder: %s", show_dir)
                self._remember_series_path(series_key, show_dir)
                created_show_folder = True
        episode_number = classification.episode or 1
        existing_season_dir = self._pick_existing_season_dir(show_dir, season_number)
        if existing_season_dir:
            season_dir = existing_season_dir
            logger.info("  [resolver] matched existing season dir: %s", existing_season_dir)
        else:
            season_dir = show_dir / f"Season {season_number:02d}"
            logger.info("  [resolver] new season dir: %s", season_dir)
        ext = Path(candidate.source_path).suffix or ".mkv"
        # Trust the folder for the show title - the episode title is not the show
        show_title = sanitize_name(classification.title or show_dir.name)
        episode_base = f"{show_title} - S{season_number:02d}E{episode_number:02d}"
        target_path = str(season_dir / f"{episode_base}{ext}")
        # Check if an existing file for this episode already exists in the season dir
        episode_tag = f"s{season_number:02d}e{episode_number:02d}"
        if season_dir.exists():
            for f in season_dir.iterdir():
                if f.name.startswith("."):
                    continue
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                    if re.search(rf"{re.escape(episode_tag)}(?:v\d+)?(?=[^a-z0-9]|$)", f.stem.lower()):
                        target_path = str(f)
                        logger.info("  [resolver] matched existing episode file: %s", target_path)
                        break
        logger.info("  [resolver] target: %s", target_path)
        self._remember_series_alias_season(series_key, classification.series_alias, season_number)
        if classification.series_alias and season_number:
            logger.info("  [resolver] remembered alias \"%s\" → season %d", classification.series_alias, season_number)

        existing_seasons = self._existing_seasons(show_dir)
        has_previous_season = bool(season_number > 1 and (season_number - 1) in existing_seasons)
        existing_episodes = self._existing_episodes_in_season(season_dir)
        has_previous_episode = bool(episode_number > 1 and (episode_number - 1) in existing_episodes)
        phantom_show_folder = bool(not show_dir.exists() and best_match is None)
        is_continuation_suspect = phantom_show_folder or (season_number > 1 and not has_previous_season)
        candidates = self._build_series_candidates(
            candidate=candidate,
            classification=classification,
            all_existing_paths=all_existing_paths,
            chosen_show_dir=show_dir,
            series_root=series_root,
            show_name=show_name,
            is_suspect=is_continuation_suspect,
        )

        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(season_dir),
            target_path=target_path,
            created_show_folder=created_show_folder,
            existing_match=best_match,
            show_folder_exists=show_dir.exists(),
            season_folder_exists=season_dir.exists(),
            phantom_show_folder=phantom_show_folder,
            has_previous_season=has_previous_season,
            max_existing_season=max(existing_seasons) if existing_seasons else None,
            has_previous_episode=has_previous_episode,
            series_key=series_key,
            season_number=season_number,
            episode_number=episode_number,
            candidate_targets=candidates,
        )

    def find_continuation_show(
        self,
        title: str,
        year: int | None,
        season: int,
        episode: int,
        episode_title: str | None,
        series_roots: list[str] | None = None,
    ) -> str | None:
        """Deep re-search for a real continuation folder when resolution produced a phantom.

        Recall tier: no token-overlap gate. Auto-pick tier: a strong signal
        (season-arc, episode-title alias, name equality/subset) plus continuity
        evidence (a season dir at or just below the target season).
        """
        if series_roots is None:
            series_roots = list(self._config.paths.series_roots.values())
        paths = list(self._series_existing_paths)
        if not self._scan_prepared:
            paths = []
            for root in series_roots:
                paths.extend(list_target_paths(root))
        if not paths:
            return None

        title_norm = normalize_series_text(title)
        title_tokens = tokenize(title)
        year_text = str(year) if year else ""
        target_arc = season_arc_text(title)
        ep_title_norm = normalize_series_text(episode_title) if episode_title else ""
        ep_title_tokens = tokenize(episode_title) if episode_title else set()
        start = time.monotonic()
        logger.info(
            "[resolver] continuation search: title=%r year=%s season=%d ep_title=%r across %d folders",
            title, year, season, episode_title, len(paths),
        )

        scored: list[tuple[float, bool, str]] = []
        # Cache seasons per path for this call to avoid repeated iterdir
        seasons_cache: dict[str, set[int]] = {}
        for path in paths:
            try:
                folder = Path(path)
                folder_name = folder.name
                folder_norm = normalize_series_text(folder_name)
                folder_tokens = tokenize(folder_name)
                # Early gate: skip most folders before any disk I/O (rglob/iterdir)
                # Keep folders that share a token, have the year, could match via arc (defer arc check), or share ep-title token
                if not (title_tokens & folder_tokens or (year_text and year_text in folder_name) or target_arc or (ep_title_tokens & folder_tokens)):
                    continue
                seasons = seasons_cache.get(path)
                if seasons is None:
                    seasons = self._existing_seasons(folder)
                    seasons_cache[path] = seasons
                prev_season_in = (season - 1) in seasons
                season_in_target = season in seasons
                year_match = bool(year_text and year_text in folder_name)
                # Re-check gate with continuity now that we have it
                if not (title_tokens & folder_tokens or year_match or prev_season_in or season_in_target or target_arc):
                    continue
                if prev_season_in:
                    continuity_bonus = 2.0
                elif seasons and max(seasons) < season:
                    continuity_bonus = 1.0
                else:
                    continuity_bonus = 0.0

                arc_match = False
                if target_arc and folder.is_dir():
                    for child in folder.iterdir():
                        if child.name.startswith(".") or not child.is_dir():
                            continue
                        arc = season_dir_arc(child.name)
                        if arc and (arc == target_arc or target_arc in arc or arc in target_arc):
                            arc_match = True
                            break

                alias_match = False
                cheap_gate = bool(
                    (title_tokens & folder_tokens)
                    or year_match
                    or prev_season_in
                    or season_in_target
                    or arc_match
                )
                if ep_title_norm and cheap_gate:
                    for alias in series_aliases(path):
                        alias_norm = normalize_series_text(alias)
                        if alias_norm and (alias_norm == ep_title_norm or ep_title_norm in alias_norm or alias_norm in ep_title_norm):
                            alias_match = True
                            break
            except OSError as exc:
                logger.warning(
                    "[resolver] continuation search: skipping folder %s (filesystem error: %s)",
                    path, exc,
                )
                continue

            name_equal = bool(folder_norm and title_norm and folder_norm == title_norm)
            name_subset = bool(title_tokens and title_tokens <= folder_tokens)
            name_contains = bool(
                title_norm and (folder_norm.startswith(title_norm) or title_norm in folder_norm)
            )
            if not (arc_match or alias_match or name_equal or name_subset or name_contains or year_match):
                continue

            score = 0.0
            if arc_match:
                score += 5.0
            if alias_match:
                score += 4.0
            if name_equal:
                score += 3.0
            elif name_subset:
                score += 2.5
            elif name_contains:
                score += 2.0
            if year_match:
                score += 1.0
            if season_in_target:
                score += 0.5
            score += continuity_bonus
            strong = bool(arc_match or alias_match or name_equal or name_subset)
            has_continuity = bool(continuity_bonus > 0.0)
            scored.append((score, bool(strong and has_continuity), path))

        logger.info("[resolver] continuation search done for %r in %.2fs, %d scored", title, time.monotonic() - start, len(scored))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        for score, eligible, path in scored:
            if eligible:
                logger.info(
                    "[resolver] continuation match for %r: %s (score=%.2f)",
                    title, path, score,
                )
                return path
        return None

    def _lookup_series_path(self, series_key: str) -> str | None:
        remembered_path = self._series_path_memory.get(series_key)
        if remembered_path and self._is_valid_series_path(remembered_path):
            return remembered_path
        if remembered_path:
            self._series_path_memory.pop(series_key, None)
        return None

    def _remember_series_path(self, series_key: str, show_dir: Path) -> None:
        self._series_path_memory[series_key] = str(show_dir)

    def _lookup_series_alias_season(self, series_key: str, series_alias: str | None) -> int | None:
        if not series_alias:
            return None
        return self._series_alias_seasons.get((series_key, normalize_series_text(series_alias)))

    def _remember_series_alias_season(self, series_key: str, series_alias: str | None, season_number: int) -> None:
        if not series_alias:
            return
        self._series_alias_seasons[(series_key, normalize_series_text(series_alias))] = season_number

    def _is_valid_series_path(self, target_path: str) -> bool:
        candidate = Path(target_path)
        for root in self._config.paths.series_roots.values():
            root_path = Path(root)
            try:
                candidate.relative_to(root_path)
                return True
            except ValueError:
                continue
        return False

    async def _pick_existing_path(
        self,
        media_kind: str,
        title: str,
        year: int | None,
        target_paths: list[str],
        desired_name: str,
    ) -> str | None:
        exact_match = self._pick_exact_path_match(
            media_kind=media_kind,
            title=title,
            target_paths=target_paths,
            desired_name=desired_name,
        )
        if exact_match:
            return exact_match

        shortlisted_paths = self._shortlist_target_paths(
            media_kind=media_kind,
            title=title,
            year=year,
            target_paths=target_paths,
            desired_name=desired_name,
        )
        if not shortlisted_paths:
            return None

        best_path, score = self._best_path_match(
            title=title,
            year=year,
            target_paths=shortlisted_paths,
            desired_name=desired_name,
        )
        if best_path and score >= self._config.model.path_confidence_threshold and self._is_safe_existing_match(title, desired_name, best_path):
            return best_path
        return None

    def _is_safe_existing_match(self, title: str, desired_name: str, target_path: str) -> bool:
        wanted_norms = {normalize_series_text(value) for value in (title, desired_name) if normalize_series_text(value)}
        wanted_tokens = [tokenize(value) for value in (title, desired_name) if tokenize(value)]
        alias_values = series_aliases(target_path) if Path(target_path).is_dir() else {Path(target_path).name}

        for alias in alias_values:
            alias_norm = normalize_series_text(alias)
            alias_tokens = tokenize(alias)
            alias_core = normalize_series_text(alias.split('(')[0].strip()) if '(' in alias else alias_norm
            if alias_norm in wanted_norms:
                return True
            if any(wn and wn in alias_norm for wn in wanted_norms):
                return True
            if alias_core and any(alias_core in wn for wn in wanted_norms):
                return True
            if any(tokens and tokens <= alias_tokens for tokens in wanted_tokens):
                return True
            if any(alias_tokens and len(alias_tokens) >= 3 and alias_tokens <= tokens for tokens in wanted_tokens):
                return True
            alias_core_tokens_check = tokenize(alias_core) if alias_core else set()
            if any(alias_core_tokens_check and len(alias_core_tokens_check) >= 3 and alias_core_tokens_check <= tokens for tokens in wanted_tokens):
                return True
            for tokens in wanted_tokens:
                if not tokens or not alias_tokens:
                    continue
                inter = len(tokens & alias_tokens)
                min_len = min(len(tokens), len(alias_tokens))
                alias_core_tokens = tokenize(alias_core) if alias_core else set()
                inter_core = len(tokens & alias_core_tokens) if alias_core_tokens else 0
                if inter >= 3 and inter >= min_len * 0.6:
                    return True
                if alias_core_tokens and inter_core >= 3 and inter_core >= min(len(alias_core_tokens), len(tokens)) * 0.6:
                    return True
        return False

    def _pick_exact_path_match(
        self,
        media_kind: str,
        title: str,
        target_paths: list[str],
        desired_name: str,
    ) -> str | None:
        normalizer = normalize_series_text if media_kind == "series" else normalize_text
        title_norm = normalizer(title)
        desired_norm = normalizer(desired_name)
        wanted = {value for value in {title_norm, desired_norm} if value}
        if not wanted:
            return None

        logger.info("  [resolver] exact path match looking for %s among %d paths", title, len(target_paths))
        for idx, path in enumerate(target_paths):
            folder_name = Path(path).name
            folder_norm = normalizer(folder_name)
            if folder_norm in wanted:
                logger.info("  [resolver] exact match via folder name: %s", path)
                return path
            if media_kind != "series":
                continue
            if not tokenize(title) & tokenize(folder_name):
                continue
            alias_values = series_aliases(path)
            if any(normalizer(alias) in wanted for alias in alias_values):
                logger.info("  [resolver] exact match via file alias in %s: %s", folder_name, path)
                return path
            if idx > 0 and idx % 50 == 0:
                logger.info("  [resolver] exact match checked %d/%d paths...", idx, len(target_paths))
        logger.info("  [resolver] no exact path match found for %s", title)
        return None

    def _shortlist_target_paths(
        self,
        media_kind: str,
        title: str,
        year: int | None,
        target_paths: list[str],
        desired_name: str,
    ) -> list[str]:
        if len(target_paths) <= MAX_AI_PATH_CHOICES:
            logger.info("  [resolver] shortlist: only %d paths, keeping all", len(target_paths))
            return target_paths
        logger.info("  [resolver] shortlist: scoring %d paths for %s", len(target_paths), title)

        title_norm = normalize_text(title)
        desired_norm = normalize_text(desired_name)
        title_tokens = tokenize(title)
        desired_tokens = tokenize(desired_name)
        year_text = str(year) if year else ""

        scored: list[tuple[float, str]] = []
        for path in target_paths:
            folder_name = Path(path).name
            if media_kind == "series" and not (tokenize(title) & tokenize(folder_name)):
                continue
            alias_values = series_aliases(path) if media_kind == "series" else {folder_name}
            folder_tokens: set[str] = set()
            best_alias_similarity = 0.0
            best_alias_starts_bonus = 0.0
            best_alias_contains_bonus = 0.0

            for alias in alias_values:
                alias_norm = normalize_text(alias)
                alias_tokens = tokenize(alias)
                alias_similarity = SequenceMatcher(None, desired_norm or title_norm, alias_norm).ratio()
                alias_core_norm = normalize_text(alias.split('(')[0].strip()) if '(' in alias else alias_norm
                alias_core_tokens = tokenize(alias_core_norm) if alias_core_norm else set()
                alias_starts_bonus = 1.0 if alias_norm.startswith(title_norm) and title_norm else 0.0
                alias_contains_bonus = 1.0 if title_norm and title_norm in alias_norm else 0.0
                alias_in_title_bonus = 1.0 if alias_norm and len(alias_tokens) >= 3 and alias_norm in title_norm else 0.0
                alias_core_in_title_bonus = 1.0 if alias_core_norm and len(alias_core_tokens) >= 3 and alias_core_norm in title_norm else 0.0
                alias_suffix_bonus = 1.0 if title_norm and len(alias_tokens) >= 3 and title_norm.endswith(alias_norm) else 0.0
                alias_core_suffix_bonus = 1.0 if title_norm and alias_core_norm and len(alias_core_tokens) >= 3 and title_norm.endswith(alias_core_norm) else 0.0
                if alias_similarity > best_alias_similarity:
                    best_alias_similarity = alias_similarity
                    best_alias_starts_bonus = alias_starts_bonus
                    best_alias_contains_bonus = max(alias_contains_bonus, alias_in_title_bonus, alias_core_in_title_bonus, alias_suffix_bonus, alias_core_suffix_bonus)
                    folder_tokens = alias_tokens
                    if alias_core_tokens and len(title_tokens & alias_core_tokens) > len(title_tokens & alias_tokens):
                        folder_tokens = alias_core_tokens

            shared_title = len(title_tokens & folder_tokens)
            shared_desired = len(desired_tokens & folder_tokens)
            similarity = best_alias_similarity
            starts_bonus = best_alias_starts_bonus
            contains_bonus = best_alias_contains_bonus
            year_bonus = 1.0 if year_text and year_text in folder_name else 0.0

            score = (shared_title * 3.0) + (shared_desired * 2.0) + (similarity * 5.0) + starts_bonus + contains_bonus + year_bonus
            if score > 0:
                scored.append((score, path))

        if not scored:
            logger.info("  [resolver] shortlist: no scored paths for %s", title)
            return []

        scored.sort(key=lambda item: (-item[0], item[1]))
        shortlisted = [path for _, path in scored[:MAX_AI_PATH_CHOICES]]
        logger.info("  [resolver] shortlist: %d candidates for %s", len(shortlisted), title)
        return shortlisted

    def _best_path_match(
        self,
        title: str,
        year: int | None,
        target_paths: list[str],
        desired_name: str,
    ) -> tuple[str | None, float]:
        if not target_paths:
            return None, 0.0

        title_norm = normalize_text(title)
        desired_norm = normalize_text(desired_name)
        title_tokens = tokenize(title)
        desired_tokens = tokenize(desired_name)
        year_text = str(year) if year else ""

        best_path: str | None = None
        best_score = 0.0
        for path in target_paths:
            folder_name = Path(path).name
            alias_values = series_aliases(path) if Path(path).is_dir() else {folder_name}

            similarity = 0.0
            shared_title = 0
            shared_desired = 0
            starts_bonus = 0.0
            contains_bonus = 0.0
            best_token_total = 1
            best_alias_exact_bonus = 0
            best_alias_subset_bonus = 0

            for alias in alias_values:
                alias_norm = normalize_text(alias)
                alias_tokens = tokenize(alias)
                alias_core_norm = normalize_text(alias.split('(')[0].strip()) if '(' in alias else alias_norm
                alias_core_tokens = tokenize(alias_core_norm) if alias_core_norm else set()
                alias_similarity = SequenceMatcher(None, desired_norm or title_norm, alias_norm).ratio()
                alias_shared_title = len(title_tokens & alias_tokens)
                alias_shared_desired = len(desired_tokens & alias_tokens)
                # also consider core tokens for long titles with arc prefix
                if alias_core_tokens:
                    alias_shared_title = max(alias_shared_title, len(title_tokens & alias_core_tokens))
                    alias_shared_desired = max(alias_shared_desired, len(desired_tokens & alias_core_tokens))
                alias_subset_bonus = 1 if title_tokens and title_tokens <= alias_tokens else 0
                # reverse: alias is subset of title (show suffix in long title) — require 3+ tokens to avoid short prefix false positives
                if alias_tokens and len(alias_tokens) >= 3 and alias_tokens <= title_tokens:
                    alias_subset_bonus = 1
                if alias_core_tokens and len(alias_core_tokens) >= 3 and alias_core_tokens <= title_tokens:
                    alias_subset_bonus = 1
                alias_exact_bonus = 1 if title_norm and title_norm == alias_norm else 0
                if (
                    alias_exact_bonus,
                    alias_subset_bonus,
                    alias_similarity,
                    alias_shared_title + alias_shared_desired,
                ) > (
                    best_alias_exact_bonus,
                    best_alias_subset_bonus,
                    similarity,
                    shared_title + shared_desired,
                ):
                    best_alias_exact_bonus = alias_exact_bonus
                    best_alias_subset_bonus = alias_subset_bonus
                    similarity = alias_similarity
                    shared_title = alias_shared_title
                    shared_desired = alias_shared_desired
                    starts_bonus = 1.0 if title_norm and alias_norm.startswith(title_norm) else 0.0
                    # also handle alias contained in title (arc+show) — require 3+ tokens to avoid short prefix false positives
                    alias_in_title = 1.0 if alias_norm and len(alias_tokens) >= 3 and alias_norm in title_norm else 0.0
                    alias_core_in_title = 1.0 if alias_core_norm and len(alias_core_tokens) >= 3 and alias_core_norm in title_norm else 0.0
                    alias_suffix = 1.0 if title_norm and len(alias_tokens) >= 3 and title_norm.endswith(alias_norm) else 0.0
                    alias_core_suffix = 1.0 if title_norm and alias_core_norm and len(alias_core_tokens) >= 3 and title_norm.endswith(alias_core_norm) else 0.0
                    contains_bonus = max(
                        1.0 if title_norm and title_norm in alias_norm else 0.0,
                        alias_in_title,
                        alias_core_in_title,
                        alias_suffix,
                        alias_core_suffix,
                    )
                    best_token_total = max(len(alias_tokens), len(alias_core_tokens), 1)

            token_overlap = (shared_title + shared_desired) / (best_token_total * 2)
            year_bonus = 1.0 if year_text and year_text in folder_name else 0.0
            subset_bonus = 0.3 if title_tokens and shared_title == len(title_tokens) else 0.0
            # also handle alias is subset of title (show suffix in long title with arc prefix)
            if best_alias_subset_bonus == 1:
                subset_bonus = 0.3
            exact_bonus = 0.15 if title_norm and similarity == 1.0 else 0.0
            depth_bonus = min(series_video_count(path), 20) * 0.01 if Path(path).is_dir() else 0.0
            # strong alias bonus for alias contained in title (arc+show) — more weight than generic contains
            strong_alias_bonus = 1.0 if contains_bonus > 0 and (shared_title >= 3 and shared_title >= min(len(title_tokens), best_token_total) * 0.6) else 0.0

            score = (similarity * 0.45) + (token_overlap * 0.2) + (year_bonus * 0.15) + (starts_bonus * 0.03) + (contains_bonus * 0.02) + subset_bonus + exact_bonus + depth_bonus + (strong_alias_bonus * 0.25)
            if score > best_score:
                best_score = score
                best_path = path

        logger.info(
            "  [resolver] best match for %s: %s (score=%.2f)",
            title, best_path or "none", best_score,
        )
        return best_path, best_score

    def _pick_existing_season_dir(self, show_dir: Path, season_number: int) -> Path | None:
        if not show_dir.exists() or not show_dir.is_dir():
            return None

        valid_names = season_dir_candidates(season_number)
        prefix_match: Path | None = None
        for child in sorted(show_dir.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            child_name = normalize_text(child.name)
            if child_name in valid_names:
                return child
            if prefix_match is None and any(child_name.startswith(name + " ") for name in valid_names):
                prefix_match = child
        return prefix_match

    @staticmethod
    def _season_number_from_name(name: str) -> int | None:
        norm = normalize_text(name)
        match = re.match(r"^(?:season\s*(\d{1,2})|s(\d{1,2}))(?=\s|$)", norm)
        if not match:
            return None
        return int(match.group(1) or match.group(2))

    def _existing_seasons(self, show_dir: Path) -> set[int]:
        if not show_dir.exists() or not show_dir.is_dir():
            return set()
        seasons = set()
        for child in show_dir.iterdir():
            if child.name.startswith(".") or not child.is_dir():
                continue
            season_number = self._season_number_from_name(child.name)
            if season_number is not None:
                seasons.add(season_number)
        return seasons

    def _existing_episodes_in_season(self, season_dir: Path) -> set[int]:
        if not season_dir.exists() or not season_dir.is_dir():
            return set()
        episodes = set()
        for f in season_dir.iterdir():
            if f.name.startswith(".") or not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            match = re.search(r"\bs\d{1,2}e(\d{1,3})\b", f.stem.lower())
            if match:
                    episodes.add(int(match.group(1)))
        return episodes

    def _build_series_candidates(
        self,
        candidate: CandidateItem,
        classification: ClassificationResult,
        all_existing_paths: list[str],
        chosen_show_dir: Path,
        series_root: str,
        show_name: str,
        is_suspect: bool,
    ) -> list[CandidateTarget]:
        title = classification.title or show_name
        season_number = classification.season or 1
        year = classification.year
        episode_title = classification.episode_title
        arc_text = season_arc_text(Path(candidate.name or "").stem)

        if is_suspect:
            recall = list(all_existing_paths)
        else:
            recall = self._shortlist_target_paths(
                media_kind="series",
                title=title,
                year=year,
                target_paths=all_existing_paths,
                desired_name=show_name,
            )

        candidates: list[CandidateTarget] = []
        seen: set[str] = set()

        def add(path: str, label: str, evidence: str, source: str = "folder", reclassify: bool = False) -> None:
            if not path or path in seen:
                return
            seen.add(path)
            candidates.append(CandidateTarget(
                path=path,
                label=label,
                evidence=evidence,
                source=source,
                reclassify_as_movie=reclassify,
            ))

        chosen_path = str(chosen_show_dir)
        add(
            chosen_path,
            chosen_show_dir.name,
            "Current selection",
            source="new" if not chosen_show_dir.exists() else "folder",
        )

        scored: list[tuple[float, str, str]] = []
        for path in recall:
            if path == chosen_path:
                continue
            score, evidence = self._score_series_candidate(
                path, title, year, season_number, episode_title, arc_text,
            )
            if score > 0:
                scored.append((score, evidence, path))

        scored.sort(key=lambda item: (-item[0], item[2]))
        for score, evidence, path in scored:
            if len(candidates) >= MAX_CANDIDATE_TARGETS:
                break
            add(path, Path(path).name, evidence)

        if len(candidates) < MAX_CANDIDATE_TARGETS:
            default_new = str(Path(series_root) / show_name)
            if default_new != chosen_path:
                add(default_new, f"New folder: {show_name}", "New folder", source="new")

        if _candidate_has_movie_marker(candidate) and len(candidates) < MAX_CANDIDATE_TARGETS:
            movie_folder = self._movie_folder_name(classification)
            movie_roots_list = list(self._config.paths.movie_roots.values())
            index = int(candidate.source_root_key.split("_")[-1]) if "_" in candidate.source_root_key else 0
            movie_root = self._pick_drive_root(candidate.source_path, movie_roots_list, index)
            add(
                str(Path(movie_root) / movie_folder),
                f"As movie: {movie_folder}",
                "Movie marker present — classify as movie",
                source="movie",
                reclassify=True,
            )
        return candidates

    def _score_series_candidate(
        self,
        path: str,
        title: str,
        year: int | None,
        season_number: int,
        episode_title: str | None,
        arc_text: str,
    ) -> tuple[float, str]:
        folder_name = Path(path).name
        title_norm = normalize_series_text(title)
        folder_norm = normalize_series_text(folder_name)
        evidence: list[str] = []
        score = 0.0

        if folder_norm and folder_norm == title_norm:
            score += 3.0
            evidence.append("name match")
        score += len(tokenize(title) & tokenize(folder_name)) * 1.5

        year_text = str(year) if year else ""
        if year_text and year_text in folder_name:
            score += 1.0
            evidence.append(f"year {year_text}")

        seasons = self._existing_seasons(Path(path))
        if seasons:
            if (season_number - 1) in seasons:
                score += 2.0
                evidence.append(f"season {season_number - 1} present")
            elif any(s < season_number for s in seasons):
                score += 1.0
                evidence.append(f"seasons {min(seasons)}-{max(seasons)}")

        if arc_text:
            arc_tokens = set(arc_text.split())
            for child in Path(path).iterdir():
                if child.name.startswith(".") or not child.is_dir():
                    continue
                dir_arc_tokens = set(season_dir_arc(child.name).split())
                if arc_tokens and (arc_tokens <= dir_arc_tokens or dir_arc_tokens <= arc_tokens):
                    score += 4.0
                    evidence.append(f"arc '{child.name}'")
                    break

        if episode_title:
            ep_norm = normalize_series_text(episode_title)
            if ep_norm and ep_norm in normalize_text(folder_name):
                score += 2.0
                evidence.append("episode title match")

        if not evidence:
            evidence.append("similar name")
        return score, "; ".join(evidence)

    def _build_movie_candidates(
        self,
        title: str,
        year: int | None,
        all_existing_paths: list[str],
        chosen_dir: Path,
        movie_root: str,
        folder_name: str,
    ) -> list[CandidateTarget]:
        recall = self._shortlist_target_paths(
            media_kind="movie",
            title=title,
            year=year,
            target_paths=all_existing_paths,
            desired_name=folder_name,
        )

        candidates: list[CandidateTarget] = []
        seen: set[str] = set()

        def add(path: str, label: str, evidence: str, source: str = "folder") -> None:
            if not path or path in seen:
                return
            seen.add(path)
            candidates.append(CandidateTarget(
                path=path,
                label=label,
                evidence=evidence,
                source=source,
            ))

        chosen_path = str(chosen_dir)
        add(
            chosen_path,
            Path(chosen_path).name,
            "Current selection",
            source="new" if not chosen_dir.exists() else "folder",
        )

        title_norm = normalize_text(title)
        scored: list[tuple[float, str, str]] = []
        for path in recall:
            if path == chosen_path:
                continue
            folder_name_at = Path(path).name
            folder_norm = normalize_text(folder_name_at)
            score = 0.0
            evidence_parts: list[str] = []
            if folder_norm and folder_norm == title_norm:
                score += 3.0
                evidence_parts.append("name match")
            score += len(tokenize(title) & tokenize(folder_name_at)) * 1.5
            year_text = str(year) if year else ""
            if year_text and year_text in folder_name_at:
                score += 1.0
                evidence_parts.append(f"year {year_text}")
            if not evidence_parts:
                evidence_parts.append("similar name")
            if score > 0:
                scored.append((score, "; ".join(evidence_parts), path))

        scored.sort(key=lambda item: (-item[0], item[2]))
        for score, evidence, path in scored:
            if len(candidates) >= MAX_CANDIDATE_TARGETS:
                break
            add(path, Path(path).name, evidence)

        if len(candidates) < MAX_CANDIDATE_TARGETS:
            default_new = str(Path(movie_root) / folder_name)
            if default_new != chosen_path:
                add(default_new, f"New folder: {folder_name}", "New folder", source="new")
        return candidates

    def _movie_folder_name(self, classification: ClassificationResult) -> str:
        title = sanitize_name(classification.title or "Unknown Movie")
        if classification.year:
            return f"{title} ({classification.year})"
        return title
