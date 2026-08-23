from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.db import get_db, init_db

DEFAULT_DB_PATH = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _generate_history_id() -> str:
    return "h_" + secrets.token_hex(6)


def append_history_group(
    scan_id: str,
    group_title: str,
    group_key: str,
    items: list[dict[str, Any]],
    confirmed_by: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Append a confirmed group to history. Returns the created group."""
    init_db(db_path)
    history_id = _generate_history_id()
    confirmed_at = _now_iso()
    conn = get_db(db_path)
    try:
        conn.execute(
            "INSERT INTO history_groups (history_id, scan_id, group_title, group_key, confirmed_at, confirmed_by) VALUES (?, ?, ?, ?, ?, ?)",
            (history_id, scan_id, group_title, group_key, confirmed_at, confirmed_by),
        )
        for item in items:
            # Ensure path_history is set
            source = item.get("sourcePath") or item.get("source_path") or ""
            target = item.get("targetPath") or item.get("target_path") or ""
            path_history = item.get("pathHistory") or item.get("path_history") or [source, target]
            if not isinstance(path_history, list):
                path_history = [source, target]
            conn.execute(
                """
                INSERT INTO history_items (history_id, confirm_id, source_path, source_folder, target_path, path_history_json, action, item_type, file_size, status, error, suspect, corrected, correction_note, cross_drive)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    item.get("confirmId") or item.get("confirm_id") or "",
                    source,
                    item.get("sourceFolder") or item.get("source_folder") or "",
                    target,
                    json.dumps(path_history),
                    item.get("action", "move"),
                    item.get("item_type") or item.get("itemType") or "movie",
                    item.get("fileSize") or item.get("file_size"),
                    item.get("status") or "moved",
                    item.get("error"),
                    1 if item.get("suspect") else 0,
                    1 if item.get("corrected") else 0,
                    item.get("correctionNote") or item.get("correction_note"),
                    1 if item.get("crossDrive") or item.get("cross_drive") else 0,
                ),
            )
        conn.commit()
        # Prune old groups if needed (keep 200)
        cur = conn.execute("SELECT history_id FROM history_groups ORDER BY confirmed_at DESC LIMIT -1 OFFSET 200")
        for row in cur.fetchall():
            conn.execute("DELETE FROM history_groups WHERE history_id = ?", (row["history_id"],))
        conn.commit()
        # Return the created group
        return {
            "history_id": history_id,
            "scan_id": scan_id,
            "group_title": group_title,
            "group_key": group_key,
            "confirmed_at": confirmed_at,
            "confirmed_by": confirmed_by,
            "items": items,
        }
    finally:
        conn.close()


def _live_item_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Compute live on-disk existence for a stored history item.

    Adds source_exists/target_exists plus the pathExists string in the same
    format as presenters.format_path_exists so the frontend PathPills component
    can be reused unchanged.
    """
    source = item.get("source_path") or ""
    target = item.get("target_path") or ""
    source_exists = bool(source) and Path(source).is_file()
    target_exists = bool(target) and Path(target).is_file()
    check = "\u2713" if target_exists else "\u2717"
    if (item.get("item_type") or "movie") == "series":
        target_path = Path(target) if target else None
        season_exists = bool(target_path and target_path.parent.is_dir())
        show_exists = bool(target_path and target_path.parent.parent.is_dir())
        item["pathExists"] = "Show %s, Season %s, File %s" % (
            "\u2713" if show_exists else "\u2717",
            "\u2713" if season_exists else "\u2717",
            check,
        )
    else:
        folder_exists = bool(target and Path(target).parent.is_dir())
        item["pathExists"] = "Folder %s, File %s" % (
            "\u2713" if folder_exists else "\u2717",
            check,
        )
    item["source_exists"] = source_exists
    item["target_exists"] = target_exists
    return item


def list_history_groups(limit: int = 50, group_title: str | None = None, db_path: Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    conn = get_db(db_path)
    try:
        if group_title:
            cur = conn.execute("SELECT * FROM history_groups WHERE group_title = ? ORDER BY confirmed_at DESC LIMIT ?", (group_title, limit))
        else:
            cur = conn.execute("SELECT * FROM history_groups ORDER BY confirmed_at DESC LIMIT ?", (limit,))
        groups = []
        for row in cur.fetchall():
            g = dict(row)
            # Get items
            cur2 = conn.execute("SELECT * FROM history_items WHERE history_id = ?", (g["history_id"],))
            items = []
            for irow in cur2.fetchall():
                item = dict(irow)
                try:
                    item["pathHistory"] = json.loads(item["path_history_json"] or "[]")
                except:
                    item["pathHistory"] = []
                items.append(_live_item_fields(item))
            g["items"] = items
            g["file_count"] = len(items)
            groups.append(g)
        return groups
    finally:
        conn.close()


def get_history_group(history_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    init_db(db_path)
    conn = get_db(db_path)
    try:
        cur = conn.execute("SELECT * FROM history_groups WHERE history_id = ?", (history_id,))
        row = cur.fetchone()
        if not row:
            return None
        group = dict(row)
        cur2 = conn.execute("SELECT * FROM history_items WHERE history_id = ?", (history_id,))
        items = []
        for irow in cur2.fetchall():
            item = dict(irow)
            try:
                item["pathHistory"] = json.loads(item["path_history_json"] or "[]")
            except:
                item["pathHistory"] = []
            items.append(_live_item_fields(item))
        group["items"] = items
        return group
    finally:
        conn.close()


def append_to_path_history(history_id: str, confirm_id: str, new_target: str, db_path: Path | None = None) -> bool:
    """Append a new target to a file's pathHistory (when retargeting from history)."""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        cur = conn.execute("SELECT path_history_json FROM history_items WHERE history_id = ? AND confirm_id = ?", (history_id, confirm_id))
        row = cur.fetchone()
        if not row:
            return False
        try:
            history = json.loads(row["path_history_json"] or "[]")
        except:
            history = []
        history.append(new_target)
        conn.execute(
            "UPDATE history_items SET target_path = ?, path_history_json = ? WHERE history_id = ? AND confirm_id = ?",
            (new_target, json.dumps(history), history_id, confirm_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def mark_undone(history_id: str, db_path: Path | None = None) -> bool:
    """Mark a history group as undone (for undo)."""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        # Add a flag to the group - we can use a separate table or just update a column
        # For now, just mark items as undone by updating status
        cur = conn.execute("UPDATE history_items SET status = 'undone' WHERE history_id = ?", (history_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_source_file(history_id: str, confirm_id: str, db_path: Path | None = None) -> dict[str, Any]:
    """Delete a leftover source file recorded in history.

    Only deletes when the exact recorded source_path still exists on disk as a
    file. Returns {deleted: bool, reason: str, source_path: str}.
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        cur = conn.execute(
            "SELECT source_path FROM history_items WHERE history_id = ? AND confirm_id = ?",
            (history_id, confirm_id),
        )
        row = cur.fetchone()
        if not row:
            return {"deleted": False, "reason": "not_found", "source_path": ""}
        source = row["source_path"]
        path = Path(source) if source else None
        if not path or not path.is_file():
            return {"deleted": False, "reason": "missing", "source_path": source}
        try:
            path.unlink()
        except OSError as exc:
            return {"deleted": False, "reason": f"error: {exc}", "source_path": source}
        return {"deleted": True, "reason": "", "source_path": source}
    finally:
        conn.close()
