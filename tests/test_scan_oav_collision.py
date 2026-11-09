import asyncio
import json
from pathlib import Path

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.models.schemas import ScanRequest
from app.services.classifier import classify_candidate
from app.services.scan_manager import ScanManager
from app.services.scanner import scan_candidates


def test_oav_batch_does_not_shadow_main_episode(tmp_path, monkeypatch):
    corpus = json.loads((Path(__file__).parent / "corpus/download_paths.json").read_text())
    entries = [e for e in corpus["candidates"] if "Marble x Lantern" in e["name"]]
    root = tmp_path / "downloads"
    for entry in entries:
        source = root / Path(entry["container_path"]).name / entry["relative_path"]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"video")
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)], seriesRoots={"s": str(tmp_path / "series")}),
        model=ModelConfig(), log_dir=tmp_path, report_dir=tmp_path,
    )
    candidates = scan_candidates(config.paths).candidates
    classified = {"OAV" if " OAV/" in c.relative_path else "main": classify_candidate(c) for c in candidates}
    assert classified["OAV"].kind == "extra"
    assert classified["OAV"].extra_type == "special"
    assert classified["main"].kind == "series"

    manager = ScanManager(config)

    async def no_refresh(_):
        pass

    monkeypatch.setattr(manager, "_trigger_jellyfin_scans", no_refresh)
    monkeypatch.setattr(
        "app.services.history_store.append_history_group",
        lambda **kwargs: {"history_id": "h_test"},
    )

    async def run():
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0.01)
        assert len(scan.items) == 2
        assert all(i.action == "move" for i in scan.items)
        assert len({i.target_path for i in scan.items}) == 2
        extra = next(i for i in scan.items if i.item_type == "extra")
        assert Path(extra.target_path).parent.name == "extras"
        tasks = []

        def track_task(coro):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        monkeypatch.setattr("app.services.scan_manager.create_task", track_task)
        await manager.confirm_scan(scan.scan_id)
        await asyncio.gather(*tasks)
        assert all(i.confirmed for i in scan.items)
        assert all(Path(i.target_path).is_file() for i in scan.items)
        assert all(not Path(i.source_path).exists() for i in scan.items)
        from app.services.presenters import format_scan_report
        assert format_scan_report(scan)["items"] == []

    asyncio.run(run())
