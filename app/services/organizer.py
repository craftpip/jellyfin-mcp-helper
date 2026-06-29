from __future__ import annotations

import json
import shutil
from datetime import datetime, UTC
from pathlib import Path

from app.core.config import AppConfig
from app.models.schemas import CandidateItem, ClassificationResult, ResolvedTarget, RunLogEntry, RunState
from app.services.classifier import classify_candidate
from app.services.jellyfin import JellyfinClient
from app.services.download_client import QbittorrentClient
from app.services.resolver import PathResolver, clear_resolver_cache
from app.services.scanner import scan_candidates


class OrganizerService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._resolver = PathResolver(config)

    async def execute(self, run_state: RunState) -> RunState:
        clear_resolver_cache()
        self._resolver.reset_runtime_state()
        scan_result = scan_candidates(self._config.paths)
        candidates = scan_result.candidates
        updated_paths: set[str] = set()
        run_state.active_step = "scan"
        run_state.active_item_path = None
        run_state.ai_thinking = ""
        run_state.ai_output = ""
        self._log(run_state, "info", "scan.started", f"Scanning found {len(candidates)} candidate items")
        run_state.counts.scanned = len(candidates)
        run_state.updated_at = datetime.now(UTC)

        for error in scan_result.errors:
            run_state.counts.failed += 1
            self._log(
                run_state,
                "error",
                "scan.path_unreadable",
                f"Filesystem read error while scanning {error.path}: {error.error}",
                item_path=error.path,
                details={"error": error.error},
            )

        in_progress_paths = await self._load_in_progress_paths(run_state)

        for candidate in candidates:
            try:
                if in_progress_paths and self._is_in_progress(candidate.source_path, in_progress_paths):
                    run_state.counts.skipped += 1
                    self._log(
                        run_state,
                        "info",
                        "candidate.in_progress",
                        f"Skipped in-progress download {candidate.name}",
                        item_path=candidate.source_path,
                        details={"reason": "download.in-progress"},
                    )
                    continue
                run_state.active_item_path = candidate.source_path
                run_state.active_step = "classify"
                run_state.ai_thinking = ""
                run_state.ai_output = ""
                classification = self._classify_candidate(candidate)
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
                changed = await self._apply_action(run_state, candidate, classification, resolved)
                if changed:
                    updated_paths.add(resolved.target_path)
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

        await self._trigger_jellyfin_scans(run_state, updated_paths)
        self._resolver.reset_runtime_state()
        clear_resolver_cache()
        return run_state

    async def _load_in_progress_paths(self, run_state: RunState) -> list[str]:
        client = QbittorrentClient.from_env()
        if not client:
            self._log(
                run_state,
                "warning",
                "download.mcp.missing",
                "QBT_MCP_URL not set; skipping in-progress download check",
            )
            return []

        try:
            paths = await client.list_in_progress_paths()
            if paths:
                self._log(
                    run_state,
                    "info",
                    "download.mcp.loaded",
                    f"Loaded {len(paths)} in-progress download paths",
                )
            return paths
        except Exception as exc:  # noqa: BLE001
            self._log(
                run_state,
                "warning",
                "download.mcp.failed",
                f"Failed to load in-progress downloads: {exc}",
            )
            return []

    @staticmethod
    def _is_in_progress(candidate_path: str, in_progress_paths: list[str]) -> bool:
        candidate_norm = str(Path(candidate_path)).rstrip("/")
        for path in in_progress_paths:
            active_norm = str(Path(path)).rstrip("/")
            if candidate_norm == active_norm:
                return True
            if candidate_norm.startswith(active_norm + "/"):
                return True
        return False

    def _classify_candidate(self, candidate: CandidateItem) -> ClassificationResult:
        return classify_candidate(candidate)

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
    ) -> bool:
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
            return False

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
            return True

        await self._stop_seeding_if_needed(run_state, candidate)

        target_dir.mkdir(parents=True, exist_ok=True)
        if target_exists:
            target_path.unlink()
        shutil.move(str(source_path), str(target_path))

        if target_exists:
            run_state.counts.replaced += 1
        else:
            run_state.counts.moved += 1

        self._cleanup_empty_parents(source_path, Path(candidate.source_root))
        return True

    async def _trigger_jellyfin_scans(self, run_state: RunState, updated_paths: set[str]) -> None:
        if run_state.dry_run or not updated_paths:
            return

        client = JellyfinClient.from_env()
        if not client:
            self._log(
                run_state,
                "warning",
                "jellyfin.scan.missing",
                "JELLYFIN_API_KEY not set; skipping Jellyfin library scan",
            )
            return

        try:
            result = await client.notify_media_updated(sorted(updated_paths))
            self._log(
                run_state,
                "info",
                "jellyfin.scan.started",
                f"Triggered Jellyfin update for {len(result.get('updated_paths', []))} path(s)",
                details={"updatedPaths": result.get("updated_paths", [])},
            )
        except Exception as exc:  # noqa: BLE001
            self._log(
                run_state,
                "error",
                "jellyfin.scan.failed",
                f"Failed to trigger Jellyfin media update: {exc}",
                details={"updatedPaths": sorted(updated_paths)},
            )

    async def _stop_seeding_if_needed(self, run_state: RunState, candidate: CandidateItem) -> None:
        client = QbittorrentClient.from_env()
        if not client:
            return

        candidate_paths = [candidate.source_path]
        if candidate.container_path:
            candidate_paths.append(candidate.container_path)

        try:
            stopped = await client.stop_seeding_for_paths(candidate_paths)
        except Exception as exc:  # noqa: BLE001
            self._log(
                run_state,
                "warning",
                "qbittorrent.stop.failed",
                f"Failed to stop seeding download before move for {candidate.name}: {exc}",
                item_path=candidate.source_path,
            )
            return

        for torrent in stopped:
            self._log(
                run_state,
                "info",
                "qbittorrent.stopped",
                f"Stopped seeding download before move: {torrent.get('name', 'unknown')}",
                item_path=candidate.source_path,
                details={
                    "torrentHash": torrent.get("hash"),
                    "torrentState": torrent.get("state_human") or torrent.get("state"),
                },
            )

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
