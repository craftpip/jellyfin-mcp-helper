"""Simple file-based scan history — keeps last N reports on disk.

Future: replace with sqlite ScanRepository, but file-based is safe and immediate
for the Vanishing knot (Phase 3.1). Reports are saved as JSON under reports/history/.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_config

HISTORY_DIR_NAME = "history"
MAX_HISTORY = 20

def history_dir(report_dir: Path | None = None) -> Path:
    # Use config report_dir / history to keep alongside existing reports dir
    d = (report_dir or get_config().report_dir) / HISTORY_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_report(scan_id: str, report: dict, report_dir: Path | None = None) -> Path:
    """Save a completed scan report to history. Prunes old entries."""
    d = history_dir(report_dir)
    path = d / f"{scan_id}.json"
    # Add saved_at
    payload = {"saved_at": datetime.now(UTC).isoformat(), **report}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    prune_history()
    return path

def list_history(limit: int = 20) -> list[dict]:
    d = history_dir()
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # Compact summary for listing
            summary = data.get("summary", {})
            out.append({
                "scan_id": summary.get("scan_id") or f.stem,
                "status": summary.get("status"),
                "saved_at": data.get("saved_at"),
                "movies": summary.get("movies"),
                "series": summary.get("series"),
                "skipped": summary.get("skipped"),
                "moved": summary.get("moved", 0),
                "replaced": summary.get("replaced", 0),
                "failed": summary.get("failed", 0),
                "action_required": summary.get("action_required"),
                "path": str(f),
            })
        except Exception:
            continue
    return out

def prune_history() -> None:
    d = history_dir()
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[MAX_HISTORY:]:
        try:
            f.unlink()
        except OSError:
            pass

def load_report(scan_id: str, report_dir: Path | None = None) -> dict | None:
    d = history_dir(report_dir)
    path = d / f"{scan_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
