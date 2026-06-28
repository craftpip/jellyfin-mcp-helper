from __future__ import annotations

import os
import re
import logging
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
import json
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

from app.core.config import AppConfig
from app.models.schemas import CandidateItem, ClassificationResult, ResolvedTarget, RunLogEntry, RunState
from app.services.scanner import list_target_paths


INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')
WORD_RE = re.compile(r"[a-z0-9]+")
MAX_AI_PATH_CHOICES = 20
EPISODE_TAG_RE = re.compile(r"\bs\d{1,2}e\d{1,3}\b.*$", re.IGNORECASE)
TRAILING_YEAR_RE = re.compile(r"\s+\d{4}$")


def sanitize_name(value: str) -> str:
    cleaned = INVALID_PATH_CHARS.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Unknown"


def normalize_text(value: str) -> str:
    return " ".join(WORD_RE.findall(value.lower()))


def normalize_series_text(value: str) -> str:
    return TRAILING_YEAR_RE.sub("", normalize_text(value)).strip()


def tokenize(value: str) -> set[str]:
    return set(WORD_RE.findall(value.lower()))


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

    sample_count = 0
    for file_path in sorted(root.rglob("*")):
        if sample_count >= 12:
            break
        if not file_path.is_file() or file_path.suffix.lower() not in {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"}:
            continue
        cleaned = EPISODE_TAG_RE.sub("", file_path.stem).strip(" -._")
        if cleaned:
            aliases.add(cleaned)
        sample_count += 1
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
        if file_path.is_file() and file_path.suffix.lower() in {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"}:
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

    def reset_runtime_state(self) -> None:
        self._series_path_memory.clear()
        self._series_alias_seasons.clear()

    async def resolve(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        if classification.kind == "movie":
            return await self._resolve_movie(candidate, classification)
        return await self._resolve_series(candidate, classification)

    async def _resolve_movie(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        index = int(candidate.source_root_key.split("_")[-1]) if "_" in candidate.source_root_key else 0
        movie_roots_list = list(self._config.paths.movie_roots.values())
        movie_root = self._pick_drive_root(candidate.source_path, movie_roots_list, index)
        
        all_existing_paths = []
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
        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(target_dir),
            target_path=target_path,
            created_movie_folder=best_match is None,
            existing_match=best_match,
            folder_exists=best_match is not None,
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
        
        all_existing_paths = []
        for root in series_roots_list:
            all_existing_paths.extend(list_target_paths(root))
        show_name = sanitize_name(classification.title or candidate.name)
        show_name = re.sub(r"([^a-zA-Z0-9])\1+$", r"\1", show_name)
        series_key = series_lookup_key(show_name, classification.year)
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
        episode_title = sanitize_name(classification.episode_title or classification.title or show_dir.name)
        episode_base = f"{episode_title} - S{season_number:02d}E{episode_number:02d}"
        target_path = str(season_dir / f"{episode_base}{ext}")
        logger.info("  [resolver] target: %s", target_path)
        self._remember_series_alias_season(series_key, classification.series_alias, season_number)
        if classification.series_alias and season_number:
            logger.info("  [resolver] remembered alias \"%s\" → season %d", classification.series_alias, season_number)
        folder_exists = show_dir.exists()
        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(season_dir),
            target_path=target_path,
            created_show_folder=created_show_folder,
            existing_match=best_match,
            folder_exists=folder_exists,
        )

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
        await self._log_resolution_shortlist(
            media_kind=media_kind,
            title=title,
            total_candidates=len(target_paths),
            shortlisted_count=len(shortlisted_paths),
            shortlisted_paths=shortlisted_paths,
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
            if alias_norm in wanted_norms:
                return True
            if any(tokens and tokens <= alias_tokens for tokens in wanted_tokens):
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

        for path in target_paths:
            folder_name = Path(path).name
            alias_values = series_aliases(path) if media_kind == "series" else {folder_name}
            if any(normalizer(alias) in wanted for alias in alias_values):
                return path
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
            return target_paths

        title_norm = normalize_text(title)
        desired_norm = normalize_text(desired_name)
        title_tokens = tokenize(title)
        desired_tokens = tokenize(desired_name)
        year_text = str(year) if year else ""

        scored: list[tuple[float, str]] = []
        for path in target_paths:
            folder_name = Path(path).name
            alias_values = series_aliases(path) if media_kind == "series" else {folder_name}
            folder_norm = ""
            folder_tokens: set[str] = set()
            best_alias_similarity = 0.0
            best_alias_starts_bonus = 0.0
            best_alias_contains_bonus = 0.0

            for alias in alias_values:
                alias_norm = normalize_text(alias)
                alias_tokens = tokenize(alias)
                alias_similarity = SequenceMatcher(None, desired_norm or title_norm, alias_norm).ratio()
                alias_starts_bonus = 1.0 if alias_norm.startswith(title_norm) and title_norm else 0.0
                alias_contains_bonus = 1.0 if title_norm and title_norm in alias_norm else 0.0
                if alias_similarity > best_alias_similarity:
                    best_alias_similarity = alias_similarity
                    best_alias_starts_bonus = alias_starts_bonus
                    best_alias_contains_bonus = alias_contains_bonus
                    folder_norm = alias_norm
                    folder_tokens = alias_tokens

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
            return []

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [path for _, path in scored[:MAX_AI_PATH_CHOICES]]

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
                alias_similarity = SequenceMatcher(None, desired_norm or title_norm, alias_norm).ratio()
                alias_shared_title = len(title_tokens & alias_tokens)
                alias_shared_desired = len(desired_tokens & alias_tokens)
                alias_subset_bonus = 1 if title_tokens and title_tokens <= alias_tokens else 0
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
                    contains_bonus = 1.0 if title_norm and title_norm in alias_norm else 0.0
                    best_token_total = max(len(alias_tokens), 1)

            token_overlap = (shared_title + shared_desired) / (best_token_total * 2)
            year_bonus = 1.0 if year_text and year_text in folder_name else 0.0
            subset_bonus = 0.3 if title_tokens and shared_title == len(title_tokens) else 0.0
            exact_bonus = 0.15 if title_norm and similarity == 1.0 else 0.0
            depth_bonus = min(series_video_count(path), 20) * 0.01 if Path(path).is_dir() else 0.0

            score = (similarity * 0.45) + (token_overlap * 0.2) + (year_bonus * 0.15) + (starts_bonus * 0.03) + (contains_bonus * 0.02) + subset_bonus + exact_bonus + depth_bonus
            if score > best_score:
                best_score = score
                best_path = path

        return best_path, best_score

    def _pick_existing_season_dir(self, show_dir: Path, season_number: int) -> Path | None:
        if not show_dir.exists() or not show_dir.is_dir():
            return None

        valid_names = season_dir_candidates(season_number)
        for child in sorted(show_dir.iterdir()):
            if not child.is_dir():
                continue
            child_name = normalize_text(child.name)
            if child_name in valid_names:
                return child
        return None

    def _movie_folder_name(self, classification: ClassificationResult) -> str:
        title = sanitize_name(classification.title or "Unknown Movie")
        if classification.year:
            return f"{title} ({classification.year})"
        return title

    async def _log_resolution_shortlist(
        self,
        media_kind: str,
        title: str,
        total_candidates: int,
        shortlisted_count: int,
        shortlisted_paths: list[str],
    ) -> None:
        return None

    def bind_run_state(self, run_state: RunState) -> None:
        async def shortlist_logger(
            media_kind: str,
            title: str,
            total_candidates: int,
            shortlisted_count: int,
            shortlisted_paths: list[str],
        ) -> None:
            entry = RunLogEntry(
                timestamp=datetime.now(UTC),
                level="info",
                event=f"ai.resolve.{media_kind}.shortlist",
                message=f"Shortlisted {shortlisted_count} of {total_candidates} {media_kind} paths for {title}",
                item_path=title,
                details={
                    "totalCandidates": total_candidates,
                    "shortlistedCount": shortlisted_count,
                    "shortlistedPaths": shortlisted_paths,
                },
            )
            run_state.logs.append(entry)
            run_state.updated_at = entry.timestamp
            if run_state.log_path:
                with Path(run_state.log_path).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry.model_dump(mode="json")) + "\n")

        self._log_resolution_shortlist = shortlist_logger
