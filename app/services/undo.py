"""Undo for confirmed scan moves (plan 3.3).

Only pure `move` actions are restorable: the target did not exist before the
confirm, so moving the file back is lossless. `replace` actions overwrote an
existing library file (os.replace), so their previous content is gone and they
are reported as not-undoable rather than half-restored.

Safety rules per item:
    - target missing            -> counted as missing (nothing to move back)
    - source exists meanwhile   -> skipped, never clobber newer content
    - source parent missing     -> recreated before the move
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

UNDOABLE_ACTIONS = ("move",)


def _iter_confirmed_moves(items: list[dict[str, Any]]):
    for item in items:
        if not item.get("confirmed"):
            continue
        if item.get("action") not in UNDOABLE_ACTIONS:
            continue
        source = item.get("source_path") or item.get("sourcePath")
        target = item.get("target_path") or item.get("targetPath")
        if source and target:
            yield Path(source), Path(target)


def undo_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Move confirmed files back from target to source. Returns a summary."""
    restored: list[str] = []
    skipped: list[dict[str, str]] = []
    missing = 0

    for source, target in _iter_confirmed_moves(items):
        if not target.is_file():
            missing += 1
            skipped.append({"path": str(target), "reason": "target missing"})
            continue
        if source.exists():
            skipped.append({"path": str(source), "reason": "source already exists"})
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(source))
        restored.append(str(source))

    return {"restored": restored, "restored_count": len(restored), "skipped": skipped, "missing": missing}


def undo_from_report(report: dict[str, Any] | None, *, report_dir: Path | None = None) -> dict[str, Any]:
    """Undo using a persisted history report; rewrites it with updated counts."""
    from app.services.scan_history import save_report

    if not report:
        return {"ok": False, "error": "scan not found"}

    result = undo_items(report.get("items", []))
    summary = report.get("summary", {})
    summary["moved"] = max(0, int(summary.get("moved") or 0) - result["restored_count"])
    summary.setdefault("undone", 0)
    summary["undone"] += result["restored_count"]
    report["summary"] = summary
    report["undo_note"] = f"Undone {result['restored_count']} move(s); replaces are not undoable."

    scan_id = report.get("scan_id") or summary.get("scan_id")
    if scan_id:
        save_report(scan_id, report, report_dir=report_dir)
    return {"ok": True, **result}


def normalize_schema_items(items: list[Any]) -> list[dict[str, Any]]:
    """Accept ScannedItem models or raw dicts with camelCase aliases."""
    out: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "model_dump"):
            data = item.model_dump(by_alias=False)
        else:
            data = dict(item)
            data["source_path"] = data.get("source_path") or data.get("sourcePath")
            data["target_path"] = data.get("target_path") or data.get("targetPath")
        out.append(data)
    return out
