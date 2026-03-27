from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
import json
from difflib import SequenceMatcher

from app.core.config import AppConfig
from app.models.schemas import CandidateItem, ClassificationResult, ResolvedTarget, RunLogEntry, RunState
from app.services.ollama import OllamaClient
from app.services.scanner import list_target_paths


INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')
WORD_RE = re.compile(r"[a-z0-9]+")
MAX_AI_PATH_CHOICES = 20


def sanitize_name(value: str) -> str:
    cleaned = INVALID_PATH_CHARS.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Unknown"


def normalize_text(value: str) -> str:
    return " ".join(WORD_RE.findall(value.lower()))


def tokenize(value: str) -> set[str]:
    return set(WORD_RE.findall(value.lower()))


class PathResolver:
    def __init__(self, config: AppConfig, ollama: OllamaClient) -> None:
        self._config = config
        self._ollama = ollama

    async def resolve(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        if classification.kind == "movie":
            return await self._resolve_movie(candidate, classification)
        return await self._resolve_series(candidate, classification)

    async def _resolve_movie(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        movie_root = self._config.paths.movie_roots[candidate.source_root_key]
        existing_paths = list_target_paths(movie_root)
        folder_name = self._movie_folder_name(classification)
        best_match = await self._pick_existing_path(
            media_kind="movie",
            title=classification.title or candidate.name,
            year=classification.year,
            target_paths=existing_paths,
            desired_name=folder_name,
        )

        ext = Path(candidate.source_path).suffix or ".mkv"
        base_dir = Path(best_match) if best_match else Path(movie_root) / folder_name
        target_dir = base_dir if base_dir.is_dir() or not base_dir.suffix else base_dir.parent
        target_path = str(target_dir / f"{folder_name}{ext}")
        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(target_dir),
            target_path=target_path,
            created_movie_folder=best_match is None,
            existing_match=best_match,
        )

    async def _resolve_series(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        series_root = self._config.paths.series_roots[candidate.source_root_key]
        existing_paths = list_target_paths(series_root)
        show_name = sanitize_name(classification.title or candidate.name)
        best_match = await self._pick_existing_path(
            media_kind="series",
            title=show_name,
            year=classification.year,
            target_paths=existing_paths,
            desired_name=show_name,
        )

        show_dir = Path(best_match) if best_match else Path(series_root) / show_name
        season_number = classification.season or 1
        episode_number = classification.episode or 1
        season_dir = show_dir / f"Season {season_number:02d}"
        ext = Path(candidate.source_path).suffix or ".mkv"
        episode_base = f"{sanitize_name(show_dir.name)} - S{season_number:02d}E{episode_number:02d}"
        target_path = str(season_dir / f"{episode_base}{ext}")
        return ResolvedTarget(
            root_key=candidate.source_root_key,
            target_dir=str(season_dir),
            target_path=target_path,
            created_show_folder=best_match is None,
            existing_match=best_match,
        )

    async def _pick_existing_path(
        self,
        media_kind: str,
        title: str,
        year: int | None,
        target_paths: list[str],
        desired_name: str,
    ) -> str | None:
        shortlisted_paths = self._shortlist_target_paths(title=title, year=year, target_paths=target_paths, desired_name=desired_name)
        await self._log_resolution_shortlist(
            media_kind=media_kind,
            title=title,
            total_candidates=len(target_paths),
            shortlisted_count=len(shortlisted_paths),
            shortlisted_paths=shortlisted_paths,
        )
        if not shortlisted_paths:
            return None

        schema = {
            "type": "object",
            "properties": {
                "selectedPath": {"type": "string"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["selectedPath", "confidence", "reason"],
        }
        prompt = (
            f"Choose the best existing {media_kind} path for this item.\n"
            f"Title: {title}\n"
            f"Year: {year}\n"
            f"Preferred new folder name if no match exists: {desired_name}\n"
            "Return an empty selectedPath if nothing is a strong enough match.\n"
            f"Candidate absolute target paths ({len(shortlisted_paths)} shortlisted from {len(target_paths)} total):\n"
            + "\n".join(shortlisted_paths)
        )
        response = await self._ollama.generate_json(
            prompt,
            schema,
            on_chunk=lambda chunk: self._update_ai_output(
                candidate_state_label=f"resolve-{media_kind}",
                item_path=title,
                thinking=chunk.get("thinking", ""),
                content=chunk.get("content", ""),
            ),
            on_retry=lambda attempt, exc: self._log_ai_retry(
                event=f"ai.resolve.{media_kind}.retry",
                message=f"Retrying {media_kind} path resolution for {title}",
                item_path=title,
                attempt=attempt,
                exc=exc,
            ),
        )
        selected = str(response.get("selectedPath", "")).strip()
        confidence = float(response.get("confidence", 0.0) or 0.0)
        if selected and selected in shortlisted_paths and confidence >= self._config.model.path_confidence_threshold:
            return selected
        return None

    def _shortlist_target_paths(
        self,
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
            folder_norm = normalize_text(folder_name)
            folder_tokens = tokenize(folder_name)

            shared_title = len(title_tokens & folder_tokens)
            shared_desired = len(desired_tokens & folder_tokens)
            similarity = SequenceMatcher(None, desired_norm or title_norm, folder_norm).ratio()
            starts_bonus = 1.0 if folder_norm.startswith(title_norm) and title_norm else 0.0
            contains_bonus = 1.0 if title_norm and title_norm in folder_norm else 0.0
            year_bonus = 1.0 if year_text and year_text in folder_name else 0.0

            score = (shared_title * 3.0) + (shared_desired * 2.0) + (similarity * 5.0) + starts_bonus + contains_bonus + year_bonus
            if score > 0:
                scored.append((score, path))

        if not scored:
            return []

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [path for _, path in scored[:MAX_AI_PATH_CHOICES]]

    def _movie_folder_name(self, classification: ClassificationResult) -> str:
        title = sanitize_name(classification.title or "Unknown Movie")
        if classification.year:
            return f"{title} ({classification.year})"
        return title

    async def _update_ai_output(self, candidate_state_label: str, item_path: str, thinking: str, content: str) -> None:
        return None

    async def _log_ai_retry(
        self,
        event: str,
        message: str,
        item_path: str,
        attempt: int,
        exc: Exception,
    ) -> None:
        return None

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
        async def updater(candidate_state_label: str, item_path: str, thinking: str, content: str) -> None:
            run_state.active_step = candidate_state_label
            run_state.active_item_path = item_path
            run_state.ai_thinking = thinking[-12000:]
            run_state.ai_output = content[-4000:]
            run_state.updated_at = datetime.now(UTC)

        async def retry_logger(event: str, message: str, item_path: str, attempt: int, exc: Exception) -> None:
            entry = RunLogEntry(
                timestamp=datetime.now(UTC),
                level="warning",
                event=event,
                message=f"{message} (retry {attempt}/{self._config.model.retry_attempts})",
                item_path=item_path,
                details={"attempt": attempt, "error": str(exc)},
            )
            run_state.logs.append(entry)
            run_state.updated_at = entry.timestamp
            if run_state.log_path:
                with Path(run_state.log_path).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry.model_dump(mode="json")) + "\n")

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

        self._update_ai_output = updater
        self._log_ai_retry = retry_logger
        self._log_resolution_shortlist = shortlist_logger
