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


class TestSseProgressStreams:
    def test_scan_stream_emits_hint_and_closes_without_scan(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get("/api/scans/progress/events")
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            body = res.text
            assert "data:" in body
            assert '"hint"' in body

    def test_confirm_stream_requires_token_when_password_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UI_PANEL_PASSWORD", "changeme")
        client, manager = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.get("/api/scans/confirm/events").status_code == 401

            token = client.post("/api/login", json={"password": "changeme"}).json()["token"]
            res = client.get("/api/scans/confirm/events", params={"token": token})
            assert res.status_code == 200
            assert "data:" in res.text


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


class TestAdminEnvEndpoints:
    def test_list_env_requires_auth(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UI_PANEL_PASSWORD", "changeme")
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.get("/api/admin/env").status_code == 401
            # api-keys endpoints removed — returns 404 even when authed
            assert client.get("/api/admin/api-keys").status_code == 404

    def test_list_env_returns_spec(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get("/api/admin/env")
            assert res.status_code == 200
            body = res.json()
            assert "spec" in body and "saved" in body and "effective" in body and "pending" in body
            keys = {e["key"] for e in body["spec"]}
            assert "MOVIE_ROOTS" in keys
            assert "JELLYSORT_MCP_TOKEN" in keys

    def test_update_env_rejects_unknown(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.post("/api/admin/env", json={"updates": {"NOPE": "x"}})
            assert res.status_code == 400
            assert "unknown setting" in res.json()["detail"]

    def test_update_env_requires_updates(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.post("/api/admin/env", json={})
            assert res.status_code == 400
            assert "updates" in res.json()["detail"]


class TestAdminApiKeyEndpoints:
    # API-keys feature removed — endpoints return 404.
    def test_full_crud_flow(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.post("/api/admin/api-keys", json={"name": "test-agent"}).status_code == 404
            assert client.get("/api/admin/api-keys").status_code == 404

    def test_missing_name_rejected(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.post("/api/admin/api-keys", json={"name": "  "}).status_code == 404

    def test_unknown_key_404(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.patch("/api/admin/api-keys/k_missing", json={"enabled": False}).status_code == 404
            assert client.delete("/api/admin/api-keys/k_missing").status_code == 404

    def test_toggle_requires_enabled(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            assert client.patch("/api/admin/api-keys/k_missing", json={}).status_code == 404



class TestBrowseAndRetarget:
    def _run_scan(self, client, tmp_path, files):
        downloads = tmp_path / "downloads"
        downloads.mkdir(exist_ok=True)
        for name in files:
            with (downloads / name).open("wb") as fh:
                fh.truncate(160 * 1024 * 1024)
        started = client.post("/api/scans", json={"replaceExisting": True})
        assert started.status_code == 200
        scan_id = started.json()["scan_id"]
        for _ in range(200):
            prog = client.get(f"/api/scans/{scan_id}/progress").json()
            if prog["status"] in ("completed", "failed"):
                break
            import time

            time.sleep(0.02)
        assert prog["status"] == "completed"
        return scan_id

    def test_browse_roots_and_listing(self, tmp_path, monkeypatch):
        series = tmp_path / "series" / "Existing Show"
        (series / "Season 05").mkdir(parents=True)
        with (series / "Season 05" / "Existing Show - S05E01.mkv").open("wb") as fh:
            fh.truncate(1024)
        (series / "Season 04").mkdir()

        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            roots = client.get("/api/browse/roots")
            assert roots.status_code == 200
            body = roots.json()
            paths = [r["path"] for r in body["roots"]]
            assert str(tmp_path / "series") in paths
            assert str(tmp_path / "movies") in paths

            listing = client.get("/api/browse", params={"path": str(tmp_path / "series")})
            assert listing.status_code == 200
            entries = listing.json()["entries"]
            assert any(e["name"] == "Existing Show" for e in entries)

            show = client.get("/api/browse", params={"path": str(series)})
            assert show.status_code == 200
            names = {e["name"]: e for e in show.json()["entries"]}
            assert "Season 05" in names
            assert names["Season 05"]["seasonNumber"] == 5
            assert names["Season 05"]["videoCount"] >= 1
            assert names["Season 04"]["seasonNumber"] == 4
            assert show.json()["parent"] == str(tmp_path / "series")

    def test_browse_rejects_non_root_and_missing_dir(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            outside = client.get("/api/browse", params={"path": "/tmp"})
            assert outside.status_code == 400
            missing = client.get("/api/browse", params={"path": str(tmp_path / "series" / "nope")})
            assert missing.status_code == 400

    def test_browse_resolve_returns_existing_target_dir(self, tmp_path, monkeypatch):
        season = tmp_path / "series" / "Show" / "Season 01"
        season.mkdir(parents=True)
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get("/api/browse/resolve", params={"target": str(season / "Show - S01E01.mkv")})
            assert res.status_code == 200
            body = res.json()
            assert body["path"] == str(season)
            assert body["target"] == str(season / "Show - S01E01.mkv")

    def test_browse_resolve_walks_up_to_nearest_existing_ancestor(self, tmp_path, monkeypatch):
        show = tmp_path / "series" / "Show"
        show.mkdir(parents=True)
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            # Season missing -> show dir.
            res = client.get(
                "/api/browse/resolve",
                params={"target": str(show / "Season 01" / "Show - S01E01.mkv")},
            )
            assert res.status_code == 200
            assert res.json()["path"] == str(show)

    def test_browse_resolve_falls_back_to_root_then_null(self, tmp_path, monkeypatch):
        (tmp_path / "series").mkdir(parents=True)
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            # Show missing -> series root.
            res = client.get(
                "/api/browse/resolve",
                params={"target": str(tmp_path / "series" / "Missing" / "Season 01" / "x.mkv")},
            )
            assert res.status_code == 200
            assert res.json()["path"] == str(tmp_path / "series")

            # Target outside every root -> null.
            outside = client.get("/api/browse/resolve", params={"target": "/tmp/x.mkv"})
            assert outside.status_code == 200
            assert outside.json()["path"] is None

            # Relative target -> 400.
            bad = client.get("/api/browse/resolve", params={"target": "relative/x.mkv"})
            assert bad.status_code == 400

    def test_browse_resolve_null_when_root_missing(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get(
                "/api/browse/resolve",
                params={"target": str(tmp_path / "series" / "Show" / "Season 01" / "x.mkv")},
            )
            assert res.status_code == 200
            assert res.json()["path"] is None

    def test_browse_exists_reports_missing_then_present(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            target = str(tmp_path / "series" / "Show" / "Season 01" / "Show - S01E01.mkv")
            missing = client.get("/api/browse/exists", params={"target": target, "kind": "series"})
            assert missing.status_code == 200
            assert missing.json()["pathExists"] == "Show ✗, Season ✗, File ✗"
            assert missing.json()["action"] == "move"

            season = tmp_path / "series" / "Show" / "Season 01"
            season.mkdir(parents=True)
            (season / "Show - S01E01.mkv").touch()
            present = client.get("/api/browse/exists", params={"target": target, "kind": "series"})
            assert present.status_code == 200
            assert present.json()["pathExists"] == "Show ✓, Season ✓, File ✓"
            assert present.json()["action"] == "replace"

    def test_browse_exists_movie_and_validation(self, tmp_path, monkeypatch):
        movie_dir = tmp_path / "movies" / "Movie (2024)"
        movie_dir.mkdir(parents=True)
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            target = str(movie_dir / "Movie (2024).mkv")
            res = client.get("/api/browse/exists", params={"target": target, "kind": "movie"})
            assert res.status_code == 200
            assert res.json()["pathExists"] == "Folder ✓, File ✗"

            outside = client.get("/api/browse/exists", params={"target": "/tmp/x.mkv", "kind": "movie"})
            assert outside.status_code == 400
            relative = client.get("/api/browse/exists", params={"target": "relative/x.mkv"})
            assert relative.status_code == 400

    def test_browse_search(self, tmp_path, monkeypatch):
        (tmp_path / "series" / "Crumpled Staircase" / "Season 01").mkdir(parents=True)
        (tmp_path / "series" / "Other Show" / "Season 01").mkdir(parents=True)
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get("/api/browse/search", params={"q": "crumpled"})
            assert res.status_code == 200
            results = res.json()["results"]
            assert any(r["name"] == "Crumpled Staircase" for r in results)
            assert not any(r["name"] == "Other Show" for r in results)
            empty = client.get("/api/browse/search", params={"q": ""})
            assert empty.json()["results"] == []

    def test_browse_search_matches_main_folders_only(self, tmp_path, monkeypatch):
        (tmp_path / "series" / "Crumpled Staircase" / "Season 01").mkdir(parents=True)
        (tmp_path / "series" / "Crumpled Staircase" / "Season 02").mkdir(parents=True)
        (tmp_path / "movies" / "Crumpled House").mkdir(parents=True)
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.get("/api/browse/search", params={"q": "crumpled"})
            assert res.status_code == 200
            results = res.json()["results"]
            names = {r["name"] for r in results}
            assert "Crumpled Staircase" in names
            assert "Crumpled House" in names
            assert not any(n.startswith("Season") for n in names)
            assert all(r["seasonNumber"] is None for r in results)

    def test_retarget_movie_item(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            scan_id = self._run_scan(client, tmp_path, ["Test Movie (2023).mkv"])
            report = client.get(f"/api/scans/{scan_id}/report").json()
            actionable = [i for i in report["items"] if i["action"] in ("move", "replace")]
            assert actionable
            item = actionable[0]
            assert item["itemType"] == "movie"

            new_dir = str(tmp_path / "movies" / "My Choice (2023)")
            res = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": item["confirmId"], "directory": new_dir},
            )
            assert res.status_code == 200
            updated_items = res.json()["items"]
            moved = next(i for i in updated_items if i["confirmId"] == item["confirmId"])
            assert moved["targetPath"].startswith(new_dir)
            assert moved["action"] == "move"
            assert moved["sourcePath"] == item["sourcePath"]

    def test_retarget_series_to_movie_and_back(self, tmp_path, monkeypatch):
        """After reclassifying a series episode as a movie, retargeting back to
        a series folder must restore the series path structure (Season subdir,
        SxxEyy filename, itemType=series)."""
        series_dir = tmp_path / "series" / "My Show"
        (series_dir / "Season 01").mkdir(parents=True)

        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            scan_id = self._run_scan(client, tmp_path, [
                "Ghost.in.the.Shell.SAC.2045.S01E07.720p.WEB.mkv"
            ])
            report = client.get(f"/api/scans/{scan_id}/report").json()
            actionable = [i for i in report["items"] if i["action"] in ("move", "replace")]
            assert actionable
            item = actionable[0]
            cid = item["confirmId"]
            assert item["itemType"] == "series"

            # Step 1: retarget to a series folder — should have Season 01
            res = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": cid, "directory": str(series_dir)},
            )
            assert res.status_code == 200
            moved = next(i for i in res.json()["items"] if i["confirmId"] == cid)
            assert "S01E07" in Path(moved["targetPath"]).name
            assert "Season 01" in moved["targetPath"]

            # Step 2: reclassify as movie → movie basename, itemType=movie
            movie_dir = tmp_path / "movies" / "Angel's Egg (1985)"
            movie_dir.mkdir(parents=True, exist_ok=True)
            res = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": cid, "directory": str(movie_dir), "reclassifyAsMovie": True},
            )
            assert res.status_code == 200
            moved = next(i for i in res.json()["items"] if i["confirmId"] == cid)
            assert moved["itemType"] == "movie"
            assert Path(moved["targetPath"]).name == "Angel's Egg (1985).mkv"

            # Step 3: retarget back to series folder — must fully restore
            # the series path structure, not just fix the filename.
            res = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": cid, "directory": str(series_dir)},
            )
            assert res.status_code == 200
            moved = next(i for i in res.json()["items"] if i["confirmId"] == cid)
            target = moved["targetPath"]
            fname = Path(target).name
            assert moved["itemType"] == "series", f"itemType should be series, got {moved['itemType']}"
            assert "S01E07" in fname, f"Expected series filename with S01E07, got: {fname}"
            assert "Angel" not in fname, f"Movie basename leaked into series target: {fname}"
            assert "Season 01" in target, f"Expected Season 01 subdirectory in: {target}"

            # Step 4: pick a season-level folder directly — show name must
            # come from the parent, not from the season folder itself.
            season_dir = series_dir / "Season 01"
            res = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": cid, "directory": str(season_dir)},
            )
            assert res.status_code == 200
            moved = next(i for i in res.json()["items"] if i["confirmId"] == cid)
            target = moved["targetPath"]
            fname = Path(target).name
            assert fname == "My Show - S01E07.mkv", f"Season-pick filename wrong: {fname}"
            assert str(season_dir) in target, f"Season dir missing from path: {target}"

    def test_retarget_validation(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            scan_id = self._run_scan(client, tmp_path, ["Test Movie (2023).mkv"])
            report = client.get(f"/api/scans/{scan_id}/report").json()
            confirm_id = [i for i in report["items"] if i["action"] in ("move", "replace")][0]["confirmId"]

            missing = client.post(
                f"/api/scans/{scan_id}/items/retarget", json={"directory": "/tmp"}
            )
            assert missing.status_code == 400

            outside = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": confirm_id, "directory": "/etc"},
            )
            assert outside.status_code == 400

            bad_combo = client.post(
                f"/api/scans/{scan_id}/items/retarget",
                json={"confirmId": confirm_id, "directory": str(tmp_path / "movies"), "applyToGroup": True, "reclassifyAsMovie": True},
            )
            assert bad_combo.status_code == 400


class TestUndoEndpoints:
    def test_undo_history_scan_restores_files_and_updates_report(self, tmp_path, monkeypatch):
        from app.services.scan_history import list_history, load_report, save_report

        client, manager = _make_client(tmp_path, monkeypatch)
        source = tmp_path / "downloads" / "Movie (2024).mkv"
        target = tmp_path / "library" / "Movie (2024).mkv"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
        scan_id = "undotest1234"

        save_report(
            scan_id,
            {
                "scan_id": scan_id,
                "status": "completed",
                "summary": {"moved": 1, "replaced": 0, "failed": 0},
                "items": [
                    {
                        "confirmId": "c1",
                        "sourcePath": str(source),
                        "name": "Movie (2024).mkv",
                        "item_type": "movie",
                        "confidence": 1.0,
                        "reason": "test",
                        "target_path": str(target),
                        "action": "move",
                        "confirmed": True,
                    }
                ],
            },
            report_dir=tmp_path,
        )

        with client:
            res = client.post(f"/api/scans/{scan_id}/undo")
            assert res.status_code == 200
            body = res.json()
            assert body["ok"] is True
            assert body["restored_count"] == 1

        assert source.is_file() and not target.exists()
        updated = load_report(scan_id, report_dir=tmp_path)
        assert updated["summary"]["moved"] == 0
        assert updated["summary"]["undone"] == 1

    def test_undo_unknown_scan_returns_404(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.post("/api/scans/doesnotexist/undo")
        assert res.status_code == 404

    def test_undo_current_without_scan_returns_404(self, tmp_path, monkeypatch):
        client, _ = _make_client(tmp_path, monkeypatch)
        with client:
            res = client.post("/api/scans/current/undo")
        assert res.status_code == 404
