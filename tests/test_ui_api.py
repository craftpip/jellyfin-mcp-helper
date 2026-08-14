from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.services.release_tracker import ReleaseTracker
from app.services.scan_manager import ScanManager
from app.ui.server import create_ui_app


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    import app.core.config as config_module

    monkeypatch.setattr(config_module, "_settings", None)
    yield


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            downloadRoots=[str(tmp_path / "downloads")],
            movieRoots={"default": str(tmp_path / "movies")},
            seriesRoots={"default": str(tmp_path / "series")},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )


def _make_manager(tmp_path: Path, monkeypatch) -> ScanManager:
    manager = ScanManager(_make_config(tmp_path))

    async def fake_load_in_progress_paths():
        return []

    monkeypatch.setattr(manager, "_load_in_progress_paths", fake_load_in_progress_paths)
    return manager


def _make_client(tmp_path: Path, monkeypatch) -> TestClient:
    manager = _make_manager(tmp_path, monkeypatch)
    app = create_ui_app(
        scan_manager=manager,
        release_tracker=ReleaseTracker(store_path=tmp_path / "ongoing_releases.json"),
    )
    return TestClient(app), manager


class TestDirectLogin:
    def test_status_reports_no_auth_required(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get("/api/status")
        assert res.status_code == 200
        body = res.json()
        assert body["service"] == "JellySort UI"
        assert body["version"]
        assert body["auth"]["required"] is False

    def test_endpoints_respond_without_token(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.get("/api/libraries").status_code == 200
            report = client.get("/api/scans/current/report")
            assert report.status_code == 200
            assert "hint" in report.json()
            progress = client.get("/api/scans/current/progress")
            assert progress.status_code == 200
            assert "hint" in progress.json()
            confirm = client.get("/api/scans/current/confirm-progress")
            assert confirm.status_code == 200
            assert "hint" in confirm.json()

    def test_unknown_scan_id_returns_404(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.get("/api/scans/nope/report").status_code == 404
            assert client.get("/api/scans/nope/progress").status_code == 404
            assert client.get("/api/scans/nope/confirm-progress").status_code == 404


class TestPasswordMode:
    def test_auth_flow(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UI_PANEL_PASSWORD", "changeme")
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            status = client.get("/api/status")
            assert status.status_code == 200
            assert status.json()["auth"]["required"] is True

            assert client.get("/api/libraries").status_code == 401
            assert client.get("/api/scans/current/report").status_code == 401

            wrong = client.post("/api/login", json={"password": "nope"})
            assert wrong.status_code == 401

            ok = client.post("/api/login", json={"password": "changeme"})
            assert ok.status_code == 200
            token = ok.json()["token"]
            assert token

            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/libraries", headers=headers).status_code == 200
            assert client.get("/api/scans/current/report", headers=headers).status_code == 200

            assert client.post("/api/logout", headers=headers).status_code == 200
            assert client.get("/api/libraries", headers=headers).status_code == 401

    def test_x_panel_token_header_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UI_PANEL_PASSWORD", "changeme")
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            token = client.post("/api/login", json={"password": "changeme"}).json()["token"]
            assert (
                client.get("/api/libraries", headers={"X-Panel-Token": token}).status_code
                == 200
            )

    def test_direct_login_returns_direct_flag_when_no_password(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.post("/api/login", json={"password": "anything"})
            assert res.status_code == 200
            body = res.json()
            assert body["directLogin"] is True
            assert body["token"] == ""


class TestScanLifecycle:
    def test_scan_report_confirm_delete_flow(self, tmp_path, monkeypatch):
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        source = downloads / "Test Movie (2023).mkv"
        with source.open("wb") as fh:
            fh.truncate(160 * 1024 * 1024)

        client, manager = _make_client(tmp_path, monkeypatch)
        with client:
            started = client.post("/api/scans", json={"replaceExisting": True})
            assert started.status_code == 200
            body = started.json()
            assert body["status"] == "running"
            assert body["scan_id"]
            scan_id = body["scan_id"]

            progress = client.get("/api/scans/current/progress")
            assert progress.status_code == 200
            assert progress.json()["scan_id"] == scan_id

            for _ in range(100):
                prog = client.get(f"/api/scans/{scan_id}/progress").json()
                if prog["status"] in ("completed", "failed"):
                    break
                import time

                time.sleep(0.02)
            assert prog["status"] == "completed"

            report = client.get(f"/api/scans/{scan_id}/report")
            assert report.status_code == 200
            items = report.json()["items"]
            actionable = [i for i in items if i["action"] in ("move", "replace")]
            assert actionable, items
            target = actionable[0]["targetPath"]

            updated = client.patch(
                f"/api/scans/{scan_id}/items",
                json={"items": [{"confirmId": actionable[0]["confirmId"], "targetPath": target}]},
            )
            assert updated.status_code == 200
            assert updated.json()["summary"]["scan_id"] == scan_id

            confirmed = client.post(
                f"/api/scans/{scan_id}/confirm",
                json={"itemIds": [actionable[0]["confirmId"]]},
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["scan_id"] == scan_id

            for _ in range(200):
                cprog = client.get(f"/api/scans/{scan_id}/confirm-progress").json()
                if cprog["status"] in ("completed", "failed", "idle"):
                    break
                import time

                time.sleep(0.02)
            assert cprog["status"] == "completed"
            assert not Path(source).exists()

            report_after = client.get(f"/api/scans/{scan_id}/report")
            assert report_after.status_code == 200
            assert report_after.json()["summary"]["status"] == "confirmed"

    def test_update_and_delete_reject_missing_input(self, tmp_path, monkeypatch):
        client, manager = _make_client(tmp_path, monkeypatch)
        with client:
            bad_update = client.patch("/api/scans/current/items", json={})
            assert bad_update.status_code == 400

            bad_delete = client.request("DELETE", "/api/scans/current/items", json={})
            assert bad_delete.status_code == 400

            bad_scan = client.post("/api/libraries/scan", json={})
            assert bad_scan.status_code == 400
