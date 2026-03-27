from __future__ import annotations

import json
import shutil
from datetime import datetime, UTC
from pathlib import Path

from app.core.config import AppConfig
from app.models.schemas import CandidateItem, ClassificationResult, ResolvedTarget, RunLogEntry, RunState
from app.services.ollama import OllamaClient
from app.services.resolver import PathResolver
from app.services.scanner import scan_candidates


class OrganizerService:
    def __init__(self, config: AppConfig, ollama: OllamaClient) -> None:
        self._config = config
        self._ollama = ollama
        self._resolver = PathResolver(config, ollama)

    async def execute(self, run_state: RunState) -> RunState:
        candidates = scan_candidates(self._config.paths)
        run_state.active_step = "scan"
        run_state.active_item_path = None
        run_state.ai_thinking = ""
        run_state.ai_output = ""
        self._log(run_state, "info", "scan.started", f"Scanning found {len(candidates)} candidate items")
        run_state.counts.scanned = len(candidates)
        run_state.updated_at = datetime.now(UTC)

        for candidate in candidates:
            try:
                run_state.active_item_path = candidate.source_path
                run_state.active_step = "classify"
                run_state.ai_thinking = ""
                run_state.ai_output = ""
                classification = await self._classify_candidate(candidate)
                run_state.counts.classified += 1
                self._log(
                    run_state,
                    "info",
                    "candidate.classified",
                    f"Classified {candidate.name} as {classification.kind}",
                    item_path=candidate.source_path,
                    details=classification.model_dump(by_alias=True),
                )

                if classification.kind == "skip" or classification.confidence < self._config.model.classify_confidence_threshold:
                    run_state.counts.skipped += 1
                    self._log(
                        run_state,
                        "warning",
                        "candidate.skipped",
                        f"Skipped {candidate.name}",
                        item_path=candidate.source_path,
                        details={
                            "reason": classification.reason,
                            "confidence": classification.confidence,
                        },
                    )
                    continue

                resolved = await self._resolver.resolve(candidate, classification)
                run_state.ai_thinking = ""
                run_state.ai_output = ""
                self._log(
                    run_state,
                    "info",
                    "target.resolved",
                    f"Resolved target for {candidate.name}",
                    item_path=candidate.source_path,
                    details=resolved.model_dump(),
                )
                await self._apply_action(run_state, candidate, classification, resolved)
            except Exception as exc:  # noqa: BLE001
                run_state.counts.failed += 1
                self._log(
                    run_state,
                    "error",
                    "candidate.failed",
                    f"Failed processing {candidate.name}: {exc}",
                    item_path=candidate.source_path,
                )

        run_state.active_step = None
        run_state.active_item_path = None
        run_state.ai_thinking = ""
        run_state.ai_output = ""

        return run_state

    async def _classify_candidate(self, candidate: CandidateItem) -> ClassificationResult:
        schema = {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["movie", "series", "skip"]},
                "title": {"type": ["string", "null"]},
                "year": {"type": ["integer", "null"]},
                "season": {"type": ["integer", "null"]},
                "episode": {"type": ["integer", "null"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["type", "title", "year", "season", "episode", "confidence", "reason"],
        }
        prompt = (
            "Classify this torrent candidate for Jellyfin organization.\n"
            f"Source path: {candidate.source_path}\n"
            f"Name: {candidate.name}\n"
            f"Extension: {candidate.extension}\n"
            f"Torrent container path: {candidate.container_path}\n"
            f"Relative path inside container: {candidate.relative_path}\n"
            "Use the filename/path semantics to decide if this is a movie, a series episode/season pack, or should be skipped. "
            "Extract the title, year, season, and episode when possible."
        )
        response = await self._ollama.generate_json(
            prompt,
            schema,
            on_chunk=lambda chunk: self._update_ai_output(
                candidate_state_label="classify",
                item_path=candidate.source_path,
                thinking=chunk.get("thinking", ""),
                content=chunk.get("content", ""),
            ),
            on_retry=lambda attempt, exc: self._log_ai_retry(
                event="ai.classify.retry",
                message=f"Retrying classification for {candidate.name}",
                item_path=candidate.source_path,
                attempt=attempt,
                exc=exc,
            ),
        )
        return ClassificationResult.model_validate(response)

    async def _update_ai_output(self, candidate_state_label: str, item_path: str, thinking: str, content: str) -> None:
        # Placeholder, rebound per run in _classify_candidate/_resolve calls.
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

    async def _apply_action(
        self,
        run_state: RunState,
        candidate: CandidateItem,
        classification: ClassificationResult,
        resolved: ResolvedTarget,
    ) -> None:
        source_path = Path(candidate.source_path)
        target_dir = Path(resolved.target_dir)
        target_path = Path(resolved.target_path)
        target_exists = target_path.exists()

        action = "replace" if target_exists else "move"
        if target_exists and not run_state.replace_existing:
            run_state.counts.skipped += 1
            self._log(
                run_state,
                "warning",
                "target.exists",
                f"Target exists, skipped {candidate.name}",
                item_path=candidate.source_path,
                details={"targetPath": str(target_path)},
            )
            return

        self._log(
            run_state,
            "info",
            "action.planned",
            f"{action.title()} planned for {candidate.name}",
            item_path=candidate.source_path,
            details={
                "dryRun": run_state.dry_run,
                "targetDir": str(target_dir),
                "targetPath": str(target_path),
                "classification": classification.model_dump(by_alias=True),
            },
        )

        if run_state.dry_run:
            if target_exists:
                run_state.counts.replaced += 1
            else:
                run_state.counts.moved += 1
            return

        target_dir.mkdir(parents=True, exist_ok=True)
        if target_exists:
            target_path.unlink()
        shutil.move(str(source_path), str(target_path))

        if target_exists:
            run_state.counts.replaced += 1
        else:
            run_state.counts.moved += 1

        self._cleanup_empty_parents(source_path, Path(candidate.source_root))

    def bind_run_state(self, run_state: RunState) -> None:
        async def updater(candidate_state_label: str, item_path: str, thinking: str, content: str) -> None:
            run_state.active_step = candidate_state_label
            run_state.active_item_path = item_path
            run_state.ai_thinking = thinking[-12000:]
            run_state.ai_output = content[-4000:]
            run_state.updated_at = datetime.now(UTC)

        async def retry_logger(event: str, message: str, item_path: str, attempt: int, exc: Exception) -> None:
            self._log(
                run_state,
                "warning",
                event,
                f"{message} (retry {attempt}/{self._config.model.retry_attempts})",
                item_path=item_path,
                details={"attempt": attempt, "error": str(exc)},
            )

        self._update_ai_output = updater
        self._log_ai_retry = retry_logger

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

    def _cleanup_empty_parents(self, original_path: Path, root_path: Path) -> None:
        current = original_path.parent
        while current != root_path and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
