from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from guessit import guessit

from app.core.config import AppConfig
from app.models.schemas import RunLogEntry, RunState
from app.services.ollama import OllamaClient


SEASON_PATTERNS = [
    re.compile(r"^s(\d{1,2})$", re.IGNORECASE),
    re.compile(r"^season\s*(\d{1,2})$", re.IGNORECASE),
    re.compile(r"^S(\d{2,})\..+", re.IGNORECASE),
    re.compile(r"^\[.+\]\s*S(\d{2,}).*", re.IGNORECASE),
]

NUMERIC_RANGE_RE = re.compile(r"\b\d{1,3}\s*-\s*\d{1,3}\b")
PROVIDER_ID_RE = re.compile(r"\[(tmdbid|tvdbid)-?\d+\]", re.IGNORECASE)
BRACKET_RE = re.compile(r"\[[^\]]+\]")

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"}

TOKEN_STRIP_RE = re.compile(
    r"\b(1080p|720p|2160p|4k|bluray|blu-ray|webrip|web-dl|webdl|dvdrip|hdrip|bdrip|brrip|x264|x265|hevc|av1|h264|h265|aac|ac3|ddp|dts|opus|dual|audio|subs|eng|hindi|japanese|multi|esub|esubs|org|atmos|10bit|8bit|12bit|proper|repack|rerip|extended|uncut|remux|hdr)\b",
    re.IGNORECASE,
)

SUFFIX_TAG_RE = re.compile(
    r"\b(1080p|720p|2160p|4k|bluray|blu-ray|webrip|web-dl|webdl|dvdrip|hdrip|bdrip|brrip|x264|x265|hevc|av1|h264|h265|aac|ac3|ddp|dts|opus|dual|audio|subs|eng|hindi|japanese|multi|esub|esubs|org|atmos|10bit|8bit|12bit|proper|repack|rerip|extended|uncut|remux|hdr)\b",
    re.IGNORECASE,
)


class NormalizerService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._ollama: OllamaClient | None = None

    async def execute(self, run_state: RunState) -> RunState:
        run_state.active_step = "normalize"
        run_state.active_item_path = None
        run_state.ai_thinking = ""
        run_state.ai_output = ""

        mode = run_state.normalize_mode
        allow_medium = run_state.allow_medium
        use_local_ai = run_state.use_local_ai

        self._log(
            run_state,
            "info",
            "normalize.started",
            f"Normalization started (mode={mode}, allowMedium={allow_medium}, useLocalAI={use_local_ai})",
        )

        for root in self._iter_series_roots():
            await self._normalize_series_root(run_state, root, mode, allow_medium, use_local_ai)

        if mode == "full":
            for root in self._iter_movie_roots():
                await self._normalize_movie_root(run_state, root, allow_medium, use_local_ai)

        run_state.active_step = None
        run_state.active_item_path = None
        run_state.ai_thinking = ""
        run_state.ai_output = ""
        return run_state

    async def _normalize_series_root(
        self,
        run_state: RunState,
        series_root: Path,
        mode: str,
        allow_medium: bool,
        use_local_ai: bool,
    ) -> None:
        if not series_root.exists():
            return

        for series_path in sorted(series_root.iterdir()):
            if not series_path.is_dir():
                continue
            run_state.active_item_path = str(series_path)

            await self._cleanup_transcoding_artifacts(run_state, series_path)
            await self._cleanup_orphan_trickplay(run_state, series_path)
            await self._normalize_season_folders(run_state, series_path)
            await self._move_root_episodes(run_state, series_path)

            if mode != "full":
                continue

            new_name, score, reason = await self._resolve_series_name(series_path.name, use_local_ai, run_state)
            if new_name and self._is_confident(score, allow_medium):
                await self._rename_path(
                    run_state,
                    series_path,
                    series_root / new_name,
                    score,
                    reason,
                )
            elif new_name:
                self._log(
                    run_state,
                    "info",
                    "normalize.series.suggested",
                    f"Suggested series name: {series_path.name} -> {new_name}",
                    item_path=str(series_path),
                    details={"confidence": score, "reason": reason},
                )

    async def _normalize_movie_root(
        self,
        run_state: RunState,
        movie_root: Path,
        allow_medium: bool,
        use_local_ai: bool,
    ) -> None:
        if not movie_root.exists():
            return

        await self._cleanup_transcoding_artifacts(run_state, movie_root)
        for item in sorted(movie_root.iterdir()):
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                await self._normalize_movie_file(run_state, item, allow_medium, use_local_ai)
                continue

            if not item.is_dir():
                continue

            for media in list(item.iterdir()):
                if media.is_file() and media.suffix.lower() in VIDEO_EXTENSIONS:
                    await self._normalize_movie_file(run_state, media, allow_medium, use_local_ai)

            new_name, score, reason = await self._resolve_movie_name(item.name, use_local_ai, run_state)
            if new_name and self._is_confident(score, allow_medium):
                await self._rename_path(
                    run_state,
                    item,
                    movie_root / new_name,
                    score,
                    reason,
                )
            elif new_name:
                self._log(
                    run_state,
                    "info",
                    "normalize.movie.suggested",
                    f"Suggested movie folder: {item.name} -> {new_name}",
                    item_path=str(item),
                    details={"confidence": score, "reason": reason},
                )

    async def _normalize_season_folders(self, run_state: RunState, series_path: Path) -> None:
        for item in list(series_path.iterdir()):
            if not item.is_dir():
                continue
            normalized = _normalize_season_name(item.name)
            if not normalized or normalized == item.name:
                continue
            target = series_path / normalized
            await self._merge_or_rename(run_state, item, target, "normalize.season")

    async def _move_root_episodes(self, run_state: RunState, series_path: Path) -> None:
        root_files = [
            item
            for item in series_path.iterdir()
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        ]
        trickplay_dirs = [
            item
            for item in series_path.iterdir()
            if item.is_dir() and item.name.endswith(".trickplay")
        ]
        if not root_files and not trickplay_dirs:
            return

        target = series_path / "Season 01"
        if not target.exists():
            self._log(
                run_state,
                "info",
                "normalize.season.created",
                f"Create Season 01 for {series_path.name}",
                item_path=str(series_path),
            )
            if not run_state.dry_run:
                target.mkdir(parents=True, exist_ok=True)

        file_target_map: dict[str, Path] = {}
        for item in root_files:
            destination = target / item.name
            await self._move_item(
                run_state,
                item,
                destination,
                "normalize.series.move_root",
            )
            file_target_map[item.stem] = destination.parent
            file_target_map[item.name] = destination.parent

        for item in trickplay_dirs:
            base_name = item.name[: -len(".trickplay")]
            destination_parent = file_target_map.get(base_name)
            if not destination_parent:
                self._log(
                    run_state,
                    "warning",
                    "normalize.trickplay.unmatched",
                    f"No matching media file for trickplay folder {item.name}",
                    item_path=str(item),
                )
                run_state.counts.skipped += 1
                continue
            await self._move_item(
                run_state,
                item,
                destination_parent / item.name,
                "normalize.series.move_root",
            )

    async def _cleanup_transcoding_artifacts(self, run_state: RunState, root: Path) -> None:
        for item in root.rglob("*__transcoding__*"):
            if not item.exists():
                continue
            await self._delete_path(run_state, item, "normalize.transcoding.removed")

    async def _cleanup_orphan_trickplay(self, run_state: RunState, series_path: Path) -> None:
        media_map: set[str] = set()
        for file_path in series_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            media_map.add(file_path.stem)
            media_map.add(file_path.name)

        for trickplay_dir in series_path.rglob("*.trickplay"):
            if not trickplay_dir.is_dir():
                continue
            base_name = trickplay_dir.name[: -len(".trickplay")]
            if base_name in media_map:
                continue
            await self._delete_path(run_state, trickplay_dir, "normalize.trickplay.orphan")

    async def _normalize_movie_file(
        self,
        run_state: RunState,
        media_path: Path,
        allow_medium: bool,
        use_local_ai: bool,
    ) -> None:
        if not media_path.is_file():
            return
        resolved, score, reason = await self._resolve_movie_name(media_path.stem, use_local_ai, run_state)
        if not resolved:
            return
        if not self._is_confident(score, allow_medium):
            self._log(
                run_state,
                "info",
                "normalize.movie.suggested",
                f"Suggested movie folder for {media_path.name}: {resolved}",
                item_path=str(media_path),
                details={"confidence": score, "reason": reason},
            )
            return

        if media_path.parent.name == resolved:
            self._log(
                run_state,
                "info",
                "normalize.movie.already",
                f"Movie already in target folder, skipped {media_path.name}",
                item_path=str(media_path),
                details={"target": str(media_path.parent)},
            )
            run_state.counts.skipped += 1
            return

        target_dir = media_path.parent / resolved
        target_path = target_dir / media_path.name
        if target_path.exists() and not run_state.replace_existing:
            self._log(
                run_state,
                "warning",
                "normalize.movie.exists",
                f"Movie target exists, skipped {media_path.name}",
                item_path=str(media_path),
                details={"target": str(target_path)},
            )
            run_state.counts.skipped += 1
            return

        if not run_state.dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        await self._move_item(run_state, media_path, target_path, "normalize.movie.move")

        base = media_path.stem
        for sidecar in media_path.parent.iterdir():
            if sidecar == media_path:
                continue
            if sidecar.is_dir():
                continue
            if sidecar.name.startswith(base + ".") or sidecar.stem == base:
                await self._move_item(run_state, sidecar, target_dir / sidecar.name, "normalize.movie.sidecar")

    async def _rename_path(
        self,
        run_state: RunState,
        source: Path,
        target: Path,
        score: float,
        reason: str,
    ) -> None:
        if source == target:
            return
        if target.exists():
            await self._merge_or_rename(run_state, source, target, "normalize.rename.merge")
            return

        self._log(
            run_state,
            "info",
            "normalize.rename",
            f"Rename {source.name} -> {target.name}",
            item_path=str(source),
            details={"confidence": score, "reason": reason, "target": str(target)},
        )
        if run_state.dry_run:
            run_state.counts.moved += 1
            return
        source.rename(target)
        run_state.counts.moved += 1

    async def _merge_or_rename(self, run_state: RunState, source: Path, target: Path, event: str) -> None:
        if source == target:
            return
        self._log(
            run_state,
            "info",
            event,
            f"Merge {source.name} -> {target.name}",
            item_path=str(source),
            details={"target": str(target)},
        )
        if run_state.dry_run:
            run_state.counts.moved += 1
            return

        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            destination = target / item.name
            if destination.exists():
                self._log(
                    run_state,
                    "warning",
                    "normalize.merge.conflict",
                    f"Conflict, skipped {item.name}",
                    item_path=str(item),
                    details={"target": str(destination)},
                )
                run_state.counts.skipped += 1
                continue
            shutil.move(str(item), str(destination))
            run_state.counts.moved += 1
        try:
            source.rmdir()
        except OSError:
            pass

    async def _move_item(self, run_state: RunState, source: Path, target: Path, event: str) -> None:
        if source == target:
            return
        if source.is_dir():
            try:
                if target.resolve().is_relative_to(source.resolve()):
                    self._log(
                        run_state,
                        "warning",
                        "normalize.move.into.self",
                        f"Skipped move into self for {source.name}",
                        item_path=str(source),
                        details={"target": str(target)},
                    )
                    run_state.counts.skipped += 1
                    return
            except RuntimeError:
                pass
        self._log(
            run_state,
            "info",
            event,
            f"Move {source.name} -> {target}",
            item_path=str(source),
        )
        if run_state.dry_run:
            run_state.counts.moved += 1
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and run_state.replace_existing:
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
        shutil.move(str(source), str(target))
        run_state.counts.moved += 1

    async def _delete_path(self, run_state: RunState, target: Path, event: str) -> None:
        self._log(
            run_state,
            "info",
            event,
            f"Remove {target.name}",
            item_path=str(target),
        )
        if run_state.dry_run:
            run_state.counts.skipped += 1
            return
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        run_state.counts.moved += 1

    async def _resolve_series_name(self, raw_name: str, use_local_ai: bool, run_state: RunState) -> tuple[str | None, float, str]:
        return await self._resolve_title(raw_name, prefer_kind="series", use_local_ai=use_local_ai, run_state=run_state)

    async def _resolve_movie_name(self, raw_name: str, use_local_ai: bool, run_state: RunState) -> tuple[str | None, float, str]:
        return await self._resolve_title(raw_name, prefer_kind="movie", use_local_ai=use_local_ai, run_state=run_state)

    @staticmethod
    def _is_confident(score: float, allow_medium: bool) -> bool:
        threshold = 0.6 if allow_medium else 0.75
        return score >= threshold

    def _iter_series_roots(self) -> Iterable[Path]:
        for root in self._config.paths.series_roots.values():
            yield Path(root)

    def _iter_movie_roots(self) -> Iterable[Path]:
        for root in self._config.paths.movie_roots.values():
            yield Path(root)

    async def _resolve_title(
        self,
        raw_name: str,
        prefer_kind: str,
        use_local_ai: bool,
        run_state: RunState,
    ) -> tuple[str | None, float, str]:
        resolved, score, reason = _resolve_title(raw_name, prefer_kind=prefer_kind)
        if score >= 0.75 or not use_local_ai:
            return resolved, score, reason

        ai = self._get_ollama_client(run_state)
        if not ai:
            return resolved, score, reason

        ai_result = await self._resolve_with_ai(ai, raw_name, prefer_kind, run_state)
        if not ai_result:
            return resolved, score, reason

        ai_title = ai_result.get("title")
        ai_year = ai_result.get("year")
        ai_kind = ai_result.get("kind")
        ai_confidence = float(ai_result.get("confidence", 0.0) or 0.0)
        ai_reason = str(ai_result.get("reason", ""))

        if ai_kind and ai_kind != prefer_kind:
            ai_confidence *= 0.8

        if NUMERIC_RANGE_RE.search(raw_name) and ai_title and not NUMERIC_RANGE_RE.search(ai_title):
            ai_confidence *= 0.4

        if not ai_title:
            return resolved, score, reason

        ai_resolved = f"{ai_title} ({ai_year})" if ai_year else ai_title
        ai_resolved = _clean_spacing(ai_resolved)
        if _is_prefix_truncation(raw_name, ai_resolved):
            return None, 0.0, "prefix-truncation"
        return ai_resolved, ai_confidence, f"ai:{ai_reason}" if ai_reason else "ai"

    def _get_ollama_client(self, run_state: RunState) -> OllamaClient | None:
        if self._ollama:
            return self._ollama
        if self._config.model.provider.lower() != "ollama":
            self._log(
                run_state,
                "warning",
                "normalize.ai.unavailable",
                "Local AI not available: model provider is not ollama",
            )
            return None
        if not self._config.model.base_url:
            self._log(
                run_state,
                "warning",
                "normalize.ai.unavailable",
                "Local AI not available: baseUrl not configured",
            )
            return None
        self._ollama = OllamaClient(self._config.model)
        return self._ollama

    async def _resolve_with_ai(
        self,
        ai: OllamaClient,
        raw_name: str,
        prefer_kind: str,
        run_state: RunState,
    ) -> dict[str, Any] | None:
        schema = {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["movie", "series", "unknown"]},
                "title": {"type": ["string", "null"]},
                "year": {"type": ["integer", "null"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["kind", "title", "year", "confidence", "reason"],
        }

        prompt = _build_ai_prompt(raw_name, prefer_kind)
        try:
            return await ai.generate_json(prompt, schema)
        except Exception as exc:  # noqa: BLE001
            self._log(
                run_state,
                "warning",
                "normalize.ai.failed",
                f"Local AI failed for '{raw_name}': {exc}",
            )
            return None

    def bind_run_state(self, run_state: RunState) -> None:
        async def updater(candidate_state_label: str, item_path: str, thinking: str, content: str) -> None:
            run_state.active_step = candidate_state_label
            run_state.active_item_path = item_path
            run_state.ai_thinking = thinking[-12000:]
            run_state.ai_output = content[-4000:]
            run_state.updated_at = datetime.now(UTC)

        self._update_ai_output = updater

    def _log(
        self,
        run_state: RunState,
        level: str,
        event: str,
        message: str,
        item_path: str | None = None,
        details: dict | None = None,
    ) -> None:
        entry = RunLogEntry(
            timestamp=datetime.now(UTC),
            level=level,
            event=event,
            message=message,
            item_path=item_path,
            details=details or {},
        )
        run_state.logs.append(entry)
        run_state.updated_at = entry.timestamp
        if run_state.log_path:
            with Path(run_state.log_path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.model_dump(mode="json")) + "\n")


def _normalize_season_name(name: str) -> str | None:
    for pattern in SEASON_PATTERNS:
        match = pattern.match(name.strip())
        if match:
            return f"Season {int(match.group(1)):02d}"
    return None


def _resolve_title(raw_name: str, prefer_kind: str) -> tuple[str | None, float, str]:
    parsed = guessit(raw_name, {"single_value": True})
    title = parsed.get("title") or parsed.get("series") or parsed.get("movie")
    year = parsed.get("year")
    provider = PROVIDER_ID_RE.search(raw_name)

    cleaned = _clean_name(raw_name)
    candidate = title if isinstance(title, str) and title.strip() else cleaned
    candidate = candidate.strip() if candidate else None

    if candidate and cleaned:
        candidate = _prefer_cleaned_title(candidate, cleaned)

    if candidate and _is_prefix_truncation(raw_name, candidate):
        return None, 0.0, "prefix-truncation"

    score = 0.3
    reason_parts = []
    if candidate:
        score += 0.25
        reason_parts.append("title")
    if year:
        score += 0.2
        reason_parts.append("year")
    if provider:
        score += 0.2
        reason_parts.append("provider-id")
    if cleaned and cleaned != raw_name:
        score += 0.1
        reason_parts.append("cleaned")
    if cleaned and candidate == cleaned and title and cleaned != title:
        reason_parts.append("cleaned-preferred")

    if NUMERIC_RANGE_RE.search(raw_name):
        score -= 0.15
        reason_parts.append("range")
    if len(BRACKET_RE.findall(raw_name)) >= 2:
        score -= 0.05
        reason_parts.append("brackets")

    score = max(0.0, min(1.0, score))
    if not candidate:
        return None, score, "no-title"

    if year:
        resolved = f"{candidate} ({year})"
    else:
        resolved = candidate

    resolved = _clean_spacing(resolved)

    if provider:
        resolved = f"{resolved} {provider.group(0)}"

    return resolved, score, ",".join(reason_parts) if reason_parts else prefer_kind


def _prefer_cleaned_title(candidate: str, cleaned: str) -> str:
    candidate_base = _strip_year_suffix(candidate)
    cleaned_base = _strip_year_suffix(cleaned)

    candidate_tokens = _title_tokens(candidate_base)
    cleaned_tokens = _title_tokens(cleaned_base)

    if not candidate_tokens or not cleaned_tokens:
        return candidate

    if cleaned_base.lower().startswith(candidate_base.lower()):
        if len(cleaned_tokens) >= len(candidate_tokens) + 2:
            return cleaned

    if candidate_base.lower() in cleaned_base.lower():
        if len(cleaned_tokens) >= len(candidate_tokens) + 3:
            return cleaned

    return candidate


def _strip_year_suffix(value: str) -> str:
    return re.sub(r"\s*\(\d{4}\)$", "", value).strip()


def _title_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9]+", value) if token]


def _is_prefix_truncation(raw_name: str, candidate: str) -> bool:
    if not raw_name or not candidate:
        return False

    base_candidate = _strip_year_suffix(candidate)
    if not base_candidate:
        return False

    raw_no_brackets = BRACKET_RE.sub("", raw_name)
    raw_spaced = raw_no_brackets.replace(".", " ")
    raw_spaced = re.sub(r"\s+", " ", raw_spaced).strip(" -_")

    if not raw_spaced.lower().startswith(base_candidate.lower()):
        return False

    if raw_spaced.lower() == base_candidate.lower():
        return False

    suffix = raw_spaced[len(base_candidate) :].strip(" -_")
    if not suffix:
        return False

    suffix = re.sub(r"\b\d{4}\b", "", suffix)
    suffix = SUFFIX_TAG_RE.sub("", suffix)
    suffix = re.sub(r"[^A-Za-z0-9]+", " ", suffix).strip()

    return bool(suffix)


def _build_ai_prompt(raw_name: str, prefer_kind: str) -> str:
    return (
        "You are a very literal helper. Return JSON only.\n"
        "Goal: Extract a clean title and year from messy media names.\n"
        "If you are unsure, return title=null and confidence below 0.5.\n"
        "Prefer the media kind passed to you unless clearly wrong.\n\n"
        "Examples:\n"
        "Input: [Judas] Black Clover (Seasons 1-4 + Extras) [BD 1080p][HEVC x265]\n"
        "Output: {\"kind\":\"series\",\"title\":\"Black Clover\",\"year\":null,\"confidence\":0.82,\"reason\":\"cleaned\"}\n\n"
        "Input: The.Big.Bang.Theory.2007.COMPLETE.SERIES.720p.AMZN.WEBRip.x264-GalaxyTV\n"
        "Output: {\"kind\":\"series\",\"title\":\"The Big Bang Theory\",\"year\":2007,\"confidence\":0.9,\"reason\":\"title+year\"}\n\n"
        "Input: [RPG-sama] Fullmetal Alchemist (2003) [BD Dual 1080p]\n"
        "Output: {\"kind\":\"series\",\"title\":\"Fullmetal Alchemist\",\"year\":2003,\"confidence\":0.86,\"reason\":\"title+year\"}\n\n"
        "Input: Chainsaw.Man.The.Movie.Reze.Arc.2025.1080p.WEBRip.x265\n"
        "Output: {\"kind\":\"movie\",\"title\":\"Chainsaw Man The Movie Reze Arc\",\"year\":2025,\"confidence\":0.78,\"reason\":\"title+year\"}\n\n"
        "Input: Chivalry of a Failed Knight (2015)\n"
        "Output: {\"kind\":\"series\",\"title\":\"Chivalry of a Failed Knight\",\"year\":2015,\"confidence\":0.9,\"reason\":\"title+year\"}\n\n"
        "Input: Ergo Proxy (2006)\n"
        "Output: {\"kind\":\"series\",\"title\":\"Ergo Proxy\",\"year\":2006,\"confidence\":0.9,\"reason\":\"title+year\"}\n\n"
        "Input: Tatsuki Fujimoto 17-26\n"
        "Output: {\"kind\":\"series\",\"title\":\"Tatsuki Fujimoto 17-26\",\"year\":null,\"confidence\":0.62,\"reason\":\"numeric range is part of title\"}\n\n"
        f"Now process this input as {prefer_kind}:\n"
        f"Input: {raw_name}\n"
        "Output:"
    )


def _clean_name(name: str) -> str:
    cleaned = BRACKET_RE.sub("", name)
    cleaned = cleaned.replace(".", " ")
    cleaned = TOKEN_STRIP_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -_")


def _clean_spacing(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\(\s*\)", "", value)
    return value.strip()
