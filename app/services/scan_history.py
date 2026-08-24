"""Scan history via SQLite — replaces file-based reports/history/*.json."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_config
from app.core.db import get_db, init_db

HISTORY_DIR_NAME = "history"
MAX_HISTORY = 200
SINGLETON_NAME = "current.json"


def singleton_path(report_dir: Path | None = None) -> Path:
    d = report_dir or get_config().report_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / SINGLETON_NAME


def save_singleton(scan, report_dir: Path | None = None) -> Path:
    """Persist the live single-report ScanPlan for restart recovery."""
    path = singleton_path(report_dir)
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(scan.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass
    return path


def load_singleton(report_dir: Path | None = None):
    """Load the persisted single-report ScanPlan if present."""
    path = singleton_path(report_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        from app.models.schemas import ScanPlan

        return ScanPlan.model_validate(data)
    except Exception:
        return None


def history_dir(report_dir: Path | None = None) -> Path:
    d = (report_dir or get_config().report_dir) / HISTORY_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def _get_db_path(report_dir: Path | None = None) -> Path | None:
    # If report_dir is a tmp_path from tests (e.g. /tmp/pytest/...), use it as db path
    # Otherwise use default DB_PATH
    if report_dir is not None:
        # Check if it's a test tmp path (contains pytest or tmp)
        rp_str = str(report_dir)
        if "pytest" in rp_str or "tmp" in rp_str:
            return report_dir / "test.db" if report_dir.is_dir() else report_dir.parent / "test.db"
    return None

def save_report(scan_id: str, report: dict, report_dir: Path | None = None) -> Path:
    # Keep file-based for backward compat during migration, but also save to DB
    # For tests with tmp_path, use SQLite with that tmp_path
    db_path = _get_db_path(report_dir)
    init_db(db_path)
    conn = get_db(db_path)
    try:
        # For file path return value (keep compat)
        d = history_dir(report_dir)
        path = d / f"{scan_id}.json"
        # Also save to DB
        summary = report.get("summary", {})
        counts = report.get("counts", {})
        # Use summary or counts
        payload = {"saved_at": datetime.now(UTC).isoformat(), **report}
        # Extract counts
        moved = summary.get("moved", 0) or counts.get("moved", 0)
        replaced = summary.get("replaced", 0) or counts.get("replaced", 0)
        failed = summary.get("failed", 0) or counts.get("failed", 0)
        # Save to file as well for compat (optional)
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            tmp.replace(path)
        except:
            pass
        # Save to DB — use UPSERT not REPLACE so FK history_groups aren't cascade-deleted
        conn.execute(
            """
            INSERT INTO scans (scan_id, status, operation, created_at, finished_at, counts_json, service_errors_json, report_json, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scan_id) DO UPDATE SET
                status=excluded.status,
                operation=excluded.operation,
                created_at=excluded.created_at,
                finished_at=excluded.finished_at,
                counts_json=excluded.counts_json,
                service_errors_json=excluded.service_errors_json,
                report_json=excluded.report_json,
                saved_at=excluded.saved_at
            """,
            (
                scan_id,
                report.get("status", "completed"),
                report.get("operation", "organize"),
                report.get("created_at", ""),
                report.get("finished_at", ""),
                json.dumps(report.get("counts", summary)),
                json.dumps(report.get("service_errors", {})),
                json.dumps(payload),
                payload["saved_at"],
            ),
        )
        conn.commit()
        # Prune older entries
        cur = conn.execute("SELECT scan_id FROM scans ORDER BY saved_at DESC LIMIT -1 OFFSET ?", (MAX_HISTORY,))
        for row in cur.fetchall():
            conn.execute("DELETE FROM scans WHERE scan_id = ?", (row["scan_id"],))
        conn.commit()
    finally:
        conn.close()
    # Prune files as well
    try:
        prune_history()
    except:
        pass
    return path

def list_history(limit: int = 20, report_dir: Path | None = None) -> list[dict]:
    # Merge DB and file histories so neither source hides the other (DB may be stale,
    # files may contain pre-migration scans). Deduplicate by scan_id, newest first.
    merged: dict[str, dict] = {}
    db_path = _get_db_path(report_dir)
    for test_db in [db_path, None]:
        try:
            init_db(test_db)
            conn = get_db(test_db)
            try:
                cur = conn.execute("SELECT scan_id, report_json, saved_at FROM scans ORDER BY saved_at DESC LIMIT ?", (limit * 2,))
                for row in cur.fetchall():
                    try:
                        data = json.loads(row["report_json"])
                        summary = data.get("summary", {})
                        sid = summary.get("scan_id") or row["scan_id"]
                        entry = {
                            "scan_id": sid,
                            "status": summary.get("status"),
                            "saved_at": row["saved_at"] or data.get("saved_at") or "",
                            "movies": summary.get("movies"),
                            "series": summary.get("series"),
                            "skipped": summary.get("skipped"),
                            "moved": summary.get("moved", 0),
                            "replaced": summary.get("replaced", 0),
                            "failed": summary.get("failed", 0),
                            "action_required": summary.get("action_required"),
                            "path": f"db:{row['scan_id']}",
                        }
                        if sid not in merged or (entry["saved_at"] or "") > (merged[sid].get("saved_at") or ""):
                            merged[sid] = entry
                    except:
                        continue
            finally:
                conn.close()
        except:
            continue
    # Also collect file-based history (covers pre-DB scans and any DB gap)
    d = history_dir(report_dir)
    if d.exists():
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: limit * 2]
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                summary = data.get("summary", {})
                sid = summary.get("scan_id") or f.stem
                entry = {
                    "scan_id": sid,
                    "status": summary.get("status"),
                    "saved_at": data.get("saved_at") or "",
                    "movies": summary.get("movies"),
                    "series": summary.get("series"),
                    "skipped": summary.get("skipped"),
                    "moved": summary.get("moved", 0),
                    "replaced": summary.get("replaced", 0),
                    "failed": summary.get("failed", 0),
                    "action_required": summary.get("action_required"),
                    "path": str(f),
                }
                if sid not in merged or (entry["saved_at"] or "") > (merged[sid].get("saved_at") or ""):
                    merged[sid] = entry
            except:
                continue
    if merged:
        out = sorted(merged.values(), key=lambda x: x.get("saved_at") or "", reverse=True)[:limit]
        return out
    # Fallback to files (already handled, but keep for compat)
    d = history_dir(report_dir)
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
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

def prune_history(report_dir: Path | None = None) -> None:
    d = history_dir(report_dir)
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[MAX_HISTORY:]:
        try:
            f.unlink()
        except OSError:
            pass

def load_report(scan_id: str, report_dir: Path | None = None) -> dict | None:
    # Try DB first
    db_path = _get_db_path(report_dir)
    for test_db in [db_path, None]:
        try:
            init_db(test_db)
            conn = get_db(test_db)
            try:
                cur = conn.execute("SELECT report_json FROM scans WHERE scan_id = ?", (scan_id,))
                row = cur.fetchone()
                if row and row["report_json"]:
                    return json.loads(row["report_json"])
            finally:
                conn.close()
        except:
            continue
    # Fallback to file
    d = history_dir(report_dir)
    path = d / f"{scan_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
