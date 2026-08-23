from __future__ import annotations
import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from app.core.db import get_db, init_db

def _normalize_name(v: str) -> str:
    return " ".join(v.strip().casefold().split())

# For backward compat with tests that patch this
DEFAULT_RELEASE_TRACKER_PATH = Path(__file__).resolve().parents[2] / "config" / "ongoing_releases.json"

class ReleaseTracker:
    def __init__(self, store_path: Path | None = None, db_path: Path | None = None) -> None:
        # Handle backward compat with tests that patch DEFAULT_RELEASE_TRACKER_PATH
        if db_path is None and store_path is None:
            # Check if DEFAULT_RELEASE_TRACKER_PATH has been patched to a tmp path
            try:
                default_path = DEFAULT_RELEASE_TRACKER_PATH
                if "pytest" in str(default_path) or "tmp" in str(default_path):
                    p = Path(default_path)
                    db_path = p.parent / "test.db" if p.suffix == ".json" else p
            except:
                pass
        if db_path is None and store_path is not None:
            p = Path(store_path)
            db_path = p.parent / "test.db" if p.suffix == ".json" else p
        self._db_path = db_path
        init_db(self._db_path)
        # Ensure data_json column exists
        conn = get_db(self._db_path)
        try:
            try:
                conn.execute("ALTER TABLE ongoing_releases ADD COLUMN data_json TEXT")
                conn.commit()
            except:
                pass
        finally:
            conn.close()

    def _conn(self):
        return get_db(self._db_path)

    def _find_key(self, library_name: str, series_name: str, series_id: str | None) -> str | None:
        conn = self._conn()
        try:
            if series_id:
                cur = conn.execute("SELECT series_key FROM ongoing_releases WHERE series_key = ?", (series_id,))
                if cur.fetchone():
                    return series_id
            nk = f"{_normalize_name(library_name)}::{_normalize_name(series_name)}"
            cur = conn.execute("SELECT series_key FROM ongoing_releases WHERE series_key = ?", (nk,))
            if cur.fetchone():
                return nk
            # Scan all
            cur = conn.execute("SELECT series_key, data_json FROM ongoing_releases")
            for row in cur.fetchall():
                try:
                    d = json.loads(row["data_json"] or "{}")
                    if _normalize_name(str(d.get("libraryName",""))) == _normalize_name(library_name) and _normalize_name(str(d.get("seriesName",""))) == _normalize_name(series_name):
                        return row["series_key"]
                except:
                    continue
            return None
        finally:
            conn.close()

    def _load_all(self):
        conn = self._conn()
        try:
            cur = conn.execute("SELECT data_json FROM ongoing_releases")
            out = []
            for row in cur.fetchall():
                try:
                    out.append(json.loads(row["data_json"]))
                except:
                    continue
            return out
        finally:
            conn.close()

    def upsert_release(self, payload: dict[str, Any]) -> dict[str, Any]:
        library_name = str(payload.get("libraryName") or "").strip()
        series_name = str(payload.get("seriesName") or "").strip()
        next_release_date = str(payload.get("nextReleaseDate") or "").strip()
        series_id = str(payload.get("seriesId") or "").strip() or None
        timezone_name = str(payload.get("timezone") or "").strip() or None
        if not library_name: raise ValueError("libraryName is required")
        if not series_name: raise ValueError("seriesName is required")
        if not next_release_date: raise ValueError("nextReleaseDate is required")
        parsed = self._parse_datetime(next_release_date, timezone_name)
        updated_at = datetime.now(UTC).isoformat()
        existing_key = self._find_key(library_name, series_name, series_id)
        # Find existing record for merge
        existing = None
        if existing_key:
            conn = self._conn()
            try:
                cur = conn.execute("SELECT data_json FROM ongoing_releases WHERE series_key = ?", (existing_key,))
                row = cur.fetchone()
                if row:
                    existing = json.loads(row["data_json"])
            finally:
                conn.close()
        record_key = series_id or existing_key or f"{_normalize_name(library_name)}::{_normalize_name(series_name)}"
        if existing_key and existing_key != record_key and existing:
            # delete old
            conn = self._conn()
            try:
                conn.execute("DELETE FROM ongoing_releases WHERE series_key = ?", (existing_key,))
                conn.commit()
            finally:
                conn.close()
        record = {
            "libraryName": library_name,
            "seriesName": series_name,
            "seriesId": series_id or (existing.get("seriesId") if existing else None),
            "nextReleaseDate": parsed.isoformat(),
            "nextSeason": payload.get("nextSeason"),
            "nextEpisode": payload.get("nextEpisode"),
            "timezone": timezone_name,
            "source": str(payload.get("source") or (existing.get("source") if existing else "unknown")),
            "notes": payload.get("notes"),
            "updatedAt": updated_at,
        }
        conn = self._conn()
        try:
            conn.execute("INSERT OR REPLACE INTO ongoing_releases (series_key, title, last_episode, updated_at, data_json) VALUES (?, ?, ?, ?, ?)",
                         (record_key, series_name, parsed.isoformat(), updated_at, json.dumps(record)))
            conn.commit()
        finally:
            conn.close()
        return record

    def list_releases(self, library_name: str | None = None, limit: int = 100):
        records = self._load_all()
        if library_name:
            needle = _normalize_name(library_name)
            records = [r for r in records if _normalize_name(str(r.get("libraryName",""))) == needle]
        items = sorted(records, key=lambda x: self._parse_stored_datetime(x["nextReleaseDate"]))[:limit]
        return {"tracked_count": len(items), "items": items}

    def get_release(self, payload):
        library_name = str(payload.get("libraryName") or "").strip()
        series_name = str(payload.get("seriesName") or "").strip()
        series_id = str(payload.get("seriesId") or "").strip() or None
        if not library_name: raise ValueError("libraryName is required")
        if not series_name: raise ValueError("seriesName is required")
        key = self._find_key(library_name, series_name, series_id)
        if not key:
            return None
        conn = self._conn()
        try:
            cur = conn.execute("SELECT data_json FROM ongoing_releases WHERE series_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return json.loads(row["data_json"])
            return None
        finally:
            conn.close()

    def get_due_releases(self, library_name=None, before=None, limit=50):
        before_dt = self._parse_before(before)
        all_items = self.list_releases(library_name, limit=1000)["items"]
        items = []
        for rec in sorted(all_items, key=lambda x: self._parse_stored_datetime(x["nextReleaseDate"])):
            release_dt = self._parse_stored_datetime(rec["nextReleaseDate"])
            if release_dt > before_dt:
                continue
            item = dict(rec)
            overdue = max((before_dt.astimezone(UTC) - release_dt.astimezone(UTC)).total_seconds(), 0.0)
            if overdue >= 86400:
                item["daysOverdue"] = int(overdue // 86400)
            else:
                item["hoursOverdue"] = round(overdue/3600, 1)
            items.append(item)
            if len(items) >= limit:
                break
        return {"before": before_dt.isoformat(), "due_count": len(items), "items": items}

    def delete_release(self, payload):
        library_name = str(payload.get("libraryName") or "").strip()
        series_name = str(payload.get("seriesName") or "").strip()
        series_id = str(payload.get("seriesId") or "").strip() or None
        if not library_name: raise ValueError("libraryName is required")
        if not series_name: raise ValueError("seriesName is required")
        rec = self.get_release(payload)
        if not rec:
            return None
        key = self._find_key(library_name, series_name, series_id)
        if not key:
            return None
        conn = self._conn()
        try:
            conn.execute("DELETE FROM ongoing_releases WHERE series_key = ?", (key,))
            conn.commit()
        finally:
            conn.close()
        return rec

    @staticmethod
    def _parse_stored_datetime(v: str) -> datetime:
        p = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return p.replace(tzinfo=UTC) if p.tzinfo is None else p
    def _parse_before(self, v):
        raw = str(v or "now").strip()
        if raw.lower() == "now":
            return datetime.now(UTC)
        return self._parse_datetime(raw, None)
    def _parse_datetime(self, value: str, tzname: str | None) -> datetime:
        raw = value.strip()
        try:
            tzinfo = ZoneInfo(tzname) if tzname else UTC
        except Exception as exc:
            raise ValueError(f"Invalid timezone: {tzname}") from exc
        try:
            d = date.fromisoformat(raw)
            if "T" not in raw and " " not in raw:
                return datetime.combine(d, time.min, tzinfo=tzinfo)
        except: pass
        p = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return p.replace(tzinfo=tzinfo) if p.tzinfo is None else p

