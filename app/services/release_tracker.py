from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import BASE_DIR


DEFAULT_RELEASE_TRACKER_PATH = BASE_DIR / "config" / "ongoing_releases.json"


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


class ReleaseTracker:
    _lock = Lock()

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = store_path or DEFAULT_RELEASE_TRACKER_PATH

    def upsert_release(self, payload: dict[str, Any]) -> dict[str, Any]:
        library_name = str(payload.get("libraryName") or "").strip()
        series_name = str(payload.get("seriesName") or "").strip()
        next_release_date = str(payload.get("nextReleaseDate") or "").strip()
        series_id = str(payload.get("seriesId") or "").strip() or None
        timezone_name = str(payload.get("timezone") or "").strip() or None

        if not library_name:
            raise ValueError("libraryName is required")
        if not series_name:
            raise ValueError("seriesName is required")
        if not next_release_date:
            raise ValueError("nextReleaseDate is required")

        parsed_release = self._parse_datetime(next_release_date, timezone_name)
        updated_at = datetime.now(UTC).isoformat()

        with self._lock:
            records = self._load_records()
            existing_key = self._find_existing_key(records, library_name, series_name, series_id)
            record_key = series_id or existing_key or self._name_key(library_name, series_name)

            if existing_key and existing_key != record_key:
                existing = records.pop(existing_key)
            else:
                existing = records.get(record_key, {})

            record = {
                "libraryName": library_name,
                "seriesName": series_name,
                "seriesId": series_id or existing.get("seriesId"),
                "nextReleaseDate": parsed_release.isoformat(),
                "nextSeason": payload.get("nextSeason"),
                "nextEpisode": payload.get("nextEpisode"),
                "timezone": timezone_name,
                "source": str(payload.get("source") or existing.get("source") or "unknown"),
                "notes": payload.get("notes"),
                "updatedAt": updated_at,
            }
            records[record_key] = record
            self._save_records(records)

        return record

    def list_releases(self, library_name: str | None = None, limit: int = 100) -> dict[str, Any]:
        records = self._filtered_records(library_name)
        items = sorted(records, key=lambda item: self._parse_stored_datetime(item["nextReleaseDate"]))[:limit]
        return {
            "tracked_count": len(items),
            "items": items,
        }

    def get_due_releases(
        self,
        library_name: str | None = None,
        before: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        before_dt = self._parse_before(before)
        items: list[dict[str, Any]] = []

        for record in sorted(self._filtered_records(library_name), key=lambda item: self._parse_stored_datetime(item["nextReleaseDate"])):
            release_dt = self._parse_stored_datetime(record["nextReleaseDate"])
            if release_dt > before_dt:
                continue
            item = dict(record)
            overdue_seconds = max((before_dt.astimezone(UTC) - release_dt.astimezone(UTC)).total_seconds(), 0.0)
            if overdue_seconds >= 86400:
                item["daysOverdue"] = int(overdue_seconds // 86400)
            else:
                item["hoursOverdue"] = round(overdue_seconds / 3600, 1)
            items.append(item)
            if len(items) >= limit:
                break

        return {
            "before": before_dt.isoformat(),
            "due_count": len(items),
            "items": items,
        }

    def delete_release(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        library_name = str(payload.get("libraryName") or "").strip()
        series_name = str(payload.get("seriesName") or "").strip()
        series_id = str(payload.get("seriesId") or "").strip() or None

        if not library_name:
            raise ValueError("libraryName is required")
        if not series_name:
            raise ValueError("seriesName is required")

        with self._lock:
            records = self._load_records()
            existing_key = self._find_existing_key(records, library_name, series_name, series_id)
            if not existing_key:
                return None
            deleted = records.pop(existing_key)
            self._save_records(records)
        return deleted

    def _filtered_records(self, library_name: str | None) -> list[dict[str, Any]]:
        records = self._load_records()
        items = list(records.values())
        if not library_name:
            return items

        needle = _normalize_name(library_name)
        return [item for item in items if _normalize_name(str(item.get("libraryName", ""))) == needle]

    def _load_records(self) -> dict[str, dict[str, Any]]:
        if not self._store_path.exists():
            return {}

        raw = self._store_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}

        data = json.loads(raw)
        records = data.get("records", {}) if isinstance(data, dict) else {}
        if not isinstance(records, dict):
            raise ValueError(f"Invalid release tracker store format: {self._store_path}")
        return {str(key): value for key, value in records.items() if isinstance(value, dict)}

    def _save_records(self, records: dict[str, dict[str, Any]]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._store_path.with_suffix(f"{self._store_path.suffix}.tmp")
        payload = {"records": records}
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(self._store_path)

    @staticmethod
    def _name_key(library_name: str, series_name: str) -> str:
        return f"{_normalize_name(library_name)}::{_normalize_name(series_name)}"

    def _find_existing_key(
        self,
        records: dict[str, dict[str, Any]],
        library_name: str,
        series_name: str,
        series_id: str | None,
    ) -> str | None:
        if series_id and series_id in records:
            return series_id

        name_key = self._name_key(library_name, series_name)
        if name_key in records:
            return name_key

        library_key = _normalize_name(library_name)
        series_key = _normalize_name(series_name)
        for record_key, record in records.items():
            if _normalize_name(str(record.get("libraryName", ""))) != library_key:
                continue
            if _normalize_name(str(record.get("seriesName", ""))) != series_key:
                continue
            return record_key
        return None

    @staticmethod
    def _parse_stored_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    def _parse_before(self, value: str | None) -> datetime:
        raw = str(value or "now").strip()
        if raw.lower() == "now":
            return datetime.now(UTC)
        return self._parse_datetime(raw, None)

    def _parse_datetime(self, value: str, timezone_name: str | None) -> datetime:
        raw = value.strip()
        tzinfo = self._resolve_timezone(timezone_name)

        try:
            parsed_date = date.fromisoformat(raw)
        except ValueError:
            parsed_date = None

        if parsed_date is not None and "T" not in raw and " " not in raw:
            return datetime.combine(parsed_date, time.min, tzinfo=tzinfo)

        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tzinfo)
        return parsed

    @staticmethod
    def _resolve_timezone(timezone_name: str | None):
        if not timezone_name:
            return UTC
        try:
            return ZoneInfo(timezone_name)
        except Exception as exc:  # pragma: no cover - invalid tz database varies by platform
            raise ValueError(f"Invalid timezone: {timezone_name}") from exc
