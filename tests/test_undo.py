from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.models.schemas import ScannedItem
from app.services.scan_manager import ScanManager
from app.services.undo import undo_items


def _item(source: Path, target: Path, action: str = "move", confirmed: bool = True) -> dict:
    return {
        "confirmId": "c1",
        "sourcePath": str(source),
        "name": source.name,
        "item_type": "movie",
        "confidence": 1.0,
        "reason": "test",
        "target_path": str(target),
        "action": action,
        "confirmed": confirmed,
    }


def test_undo_moves_file_back_and_recreates_missing_parent(tmp_path):
    library = tmp_path / "library" / "Movie (2024)"
    library.mkdir(parents=True)
    target = library / "Movie (2024).mkv"
    target.write_bytes(b"x")
    source = tmp_path / "downloads" / "Movie (2024).mkv"

    result = undo_items([_item(source, target)])

    assert result["restored_count"] == 1
    assert source.is_file()
    assert not target.exists()


def test_undo_never_clobbers_existing_source_and_counts_missing(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    source = downloads / "a.mkv"
    source.write_bytes(b"new")
    target = tmp_path / "library" / "a.mkv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"moved")

    gone_target = tmp_path / "library2" / "gone.mkv"

    result = undo_items([_item(source, target), _item(downloads / "b.mkv", gone_target)])

    assert result["restored_count"] == 0
    assert result["skipped"][0]["reason"] == "source already exists"
    assert result["missing"] == 1
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"moved"


def test_undo_ignores_replaces_and_unconfirmed(tmp_path):
    src = tmp_path / "s.mkv"
    tgt = tmp_path / "t.mkv"
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_bytes(b"x")

    result = undo_items([
        _item(src, tgt, action="replace"),
        _item(src, tgt, confirmed=False),
    ])

    assert result["restored_count"] == 0
    assert tgt.exists()


def test_manager_undo_memory_decrements_counts_and_repersists(tmp_path):
    source = tmp_path / "download.mkv"
    target = tmp_path / "library" / "download.mkv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"v")

    manager = ScanManager(
        AppConfig(paths=PathsConfig(downloadRoots=[]), model=ModelConfig(), log_dir=tmp_path, report_dir=tmp_path)
    )

    async def run_test():
        scan = await manager.create_scan(__import__("app.models.schemas", fromlist=["ScanRequest"]).ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(source),
                name=source.name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(target),
                action="move",
            )
        ]
        scan.items[0].confirmed = True
        scan.counts.movies = 1
        scan.counts.moved = 1
        return scan

    scan = asyncio.run(run_test())

    result = manager.undo_scan(scan.scan_id)

    assert result["ok"] is True
    assert result["restored_count"] == 1
    assert source.is_file() and not target.exists()
    assert scan.counts.moved == 0
