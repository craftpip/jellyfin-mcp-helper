from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.services.history_store import (
    append_history_group,
    delete_source_file,
    get_history_group,
    list_history_groups,
)
from app.services.release_tracker import ReleaseTracker
from app.services.scan_manager import ScanManager
from app.ui.server import create_ui_app


def _make_client(tmp_path: Path, monkeypatch) -> TestClient:
    # UI history routes use the module-level DB_PATH — isolate it per test.
    import app.core.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "ui-app.db")
    config = AppConfig(
        paths=PathsConfig(
            downloadRoots=[str(tmp_path / "downloads")],
            movieRoots={"default": str(tmp_path / "movies")},
            seriesRoots={"default": str(tmp_path / "series")},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)
    app = create_ui_app(
        scan_manager=manager,
        release_tracker=ReleaseTracker(store_path=tmp_path / "ongoing_releases.json"),
    )
    return TestClient(app)


def _seed_scan(db_path: Path, scan_id: str) -> None:
    from app.core.db import get_db, init_db

    init_db(db_path)
    conn = get_db(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO scans (scan_id, status, operation, created_at, finished_at, counts_json, service_errors_json, report_json, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, "completed", "organize", "now", "now", "{}", "{}", "{}", "now"),
        )
        conn.commit()
    finally:
        conn.close()


def _series_item(tmp_path: Path, *, moved: bool = True) -> dict:
    source = tmp_path / "downloads" / "Show.S01E01.mkv"
    target = tmp_path / "library" / "Show" / "Season 01" / "Show S01E01.mkv"
    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if moved:
        target.write_bytes(b"x" * 2048)
    else:
        source.write_bytes(b"x" * 2048)
    return {
        "confirmId": "c1",
        "sourcePath": str(source),
        "sourceFolder": "downloads",
        "targetPath": str(target),
        "pathHistory": [str(source), str(target)],
        "action": "move",
        "item_type": "series",
        "fileSize": 2048,
        "status": "moved",
        "suspect": True,
        "corrected": True,
        "correctionNote": "merged into existing show folder",
        "crossDrive": True,
    }


class TestHistoryStoreFlags:
    def test_persists_and_returns_flags(self, tmp_path):
        db = tmp_path / "app.db"
        target = Path(_series_item(tmp_path)["targetPath"])
        _seed_scan(db, "scan1")
        append_history_group(
            scan_id="scan1",
            group_title="Show",
            group_key=str(target.parent.parent),
            items=[_series_item(tmp_path)],
            db_path=db,
        )
        groups = list_history_groups(db_path=db)
        assert len(groups) == 1
        item = groups[0]["items"][0]
        assert item["suspect"] == 1
        assert item["corrected"] == 1
        assert item["correction_note"] == "merged into existing show folder"
        assert item["cross_drive"] == 1

    def test_live_fields_series_target_exists(self, tmp_path):
        db = tmp_path / "app.db"
        _seed_scan(db, "scan1")
        append_history_group(
            scan_id="scan1",
            group_title="Show",
            group_key="k",
            items=[_series_item(tmp_path)],
            db_path=db,
        )
        item = list_history_groups(db_path=db)[0]["items"][0]
        assert item["target_exists"] is True
        assert item["source_exists"] is False
        # show folder + season folder + file all exist
        assert item["pathExists"] == "Show \u2713, Season \u2713, File \u2713"

    def test_live_fields_movie_missing_file(self, tmp_path):
        db = tmp_path / "app.db"
        _seed_scan(db, "scan2")
        source = tmp_path / "downloads" / "Movie.mkv"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"x")
        target = tmp_path / "library" / "Movie (2020)" / "Movie (2020).mkv"
        target.parent.mkdir(parents=True, exist_ok=True)
        _seed_scan(db, "scan1")
        append_history_group(
            scan_id="scan2",
            group_title="Movie",
            group_key="k",
            items=[
                {
                    "confirmId": "m1",
                    "sourcePath": str(source),
                    "sourceFolder": "downloads",
                    "targetPath": str(target),
                    "action": "move",
                    "item_type": "movie",
                    "fileSize": 10,
                    "status": "moved",
                }
            ],
            db_path=db,
        )
        item = list_history_groups(db_path=db)[0]["items"][0]
        # target file was never created; folder exists though
        assert item["target_exists"] is False
        assert item["pathExists"] == "Folder \u2713, File \u2717"

    def test_get_history_group_matches_list(self, tmp_path):
        db = tmp_path / "app.db"
        _seed_scan(db, "scan1")
        created = append_history_group(
            scan_id="scan1",
            group_title="Show",
            group_key="k",
            items=[_series_item(tmp_path)],
            db_path=db,
        )
        group = get_history_group(created["history_id"], db_path=db)
        assert group is not None
        item = group["items"][0]
        assert item["cross_drive"] == 1
        assert "pathExists" in item


class TestDeleteSourceFile:
    def test_deletes_existing_source(self, tmp_path):
        db = tmp_path / "app.db"
        item = _series_item(tmp_path, moved=False)
        _seed_scan(db, "scan1")
        append_history_group(
            scan_id="scan1", group_title="Show", group_key="k", items=[item], db_path=db
        )
        res = delete_source_file("nonexistent", "c1", db_path=db)
        assert res["deleted"] is False and res["reason"] == "not_found"

        res = delete_source_file(
            list_history_groups(db_path=db)[0]["history_id"], "c1", db_path=db
        )
        assert res["deleted"] is True
        assert not Path(item["sourcePath"]).exists()

    def test_missing_source_reports_missing(self, tmp_path):
        db = tmp_path / "app.db"
        _seed_scan(db, "scan1")
        append_history_group(
            scan_id="scan1", group_title="Show", group_key="k", items=[_series_item(tmp_path)], db_path=db
        )
        history_id = list_history_groups(db_path=db)[0]["history_id"]
        res = delete_source_file(history_id, "c1", db_path=db)
        assert res["deleted"] is False and res["reason"] == "missing"


class TestDeleteSourceEndpoint:
    def test_delete_source_via_api(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        item = _series_item(tmp_path, moved=False)
        _seed_scan(None, "scan1")
        created = append_history_group(
            scan_id="scan1", group_title="Show", group_key="k", items=[item]
        )
        with client:
            ok = client.post(f"/api/history/{created['history_id']}/delete-source", json={"confirmId": "c1"})
            assert ok.status_code == 200
            assert ok.json()["deleted"] is True

            missing_item = client.post(
                f"/api/history/{created['history_id']}/delete-source", json={"confirmId": "nope"}
            )
            assert missing_item.status_code == 404

            no_body = client.post(
                f"/api/history/{created['history_id']}/delete-source", json={}
            )
            assert no_body.status_code == 400

            gone = client.post("/api/history/h_zzz/delete-source", json={"confirmId": "c1"})
            assert gone.status_code == 404

    def test_history_endpoint_returns_flags_and_live_fields(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        _seed_scan(None, "scan1")
        append_history_group(
            scan_id="scan1", group_title="Show", group_key="k", items=[_series_item(tmp_path)]
        )
        with client:
            res = client.get("/api/history")
        assert res.status_code == 200
        groups = res.json()["groups"]
        assert len(groups) == 1
        item = groups[0]["items"][0]
        assert item["suspect"] == 1
        assert item["cross_drive"] == 1
        assert item["target_exists"] is True
        assert "File \u2713" in item["pathExists"]
