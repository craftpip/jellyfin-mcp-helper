from __future__ import annotations

from pathlib import Path

import pytest

from app.services.api_key_manager import ApiKeyManager, KEY_PREFIX


@pytest.fixture
def manager(tmp_path: Path) -> ApiKeyManager:
    return ApiKeyManager(keys_file=str(tmp_path / "mcp_keys.json"))


class TestCreateAndList:
    def test_create_returns_full_key_once(self, manager):
        result = manager.create_key("laptop")
        assert result["name"] == "laptop"
        assert result["user"] == "default"
        assert result["scopes"] == ["*"]
        assert result["enabled"] is True
        assert result["key"].startswith(KEY_PREFIX)
        assert result["key_prefix"] == result["key"][:12]
        assert result["key_suffix"] == result["key"][-4:]
        assert "key_hash" not in result

    def test_stored_record_is_hashed(self, manager):
        result = manager.create_key("laptop")
        data = manager._load()
        record = data["keys"][0]
        assert record["key_hash"].startswith("sha256:")
        assert result["key"] not in record["key_hash"]
        assert record["key_hash"] != result["key"]

    def test_list_never_exposes_hash_or_full_key(self, manager):
        manager.create_key("laptop")
        keys = manager.list_keys()
        assert len(keys) == 1
        assert "key_hash" not in keys[0]
        assert "key" not in keys[0]
        assert len(keys[0]["key_suffix"]) == 4

    def test_multiple_keys_and_default_scopes(self, manager):
        a = manager.create_key("a", user="alice", scopes=["scan"])
        b = manager.create_key("b")
        assert a["scopes"] == ["scan"]
        assert b["scopes"] == ["*"]
        assert len(manager.list_keys()) == 2

    def test_create_rejects_empty_name(self, manager):
        with pytest.raises(ValueError):
            manager.create_key("  ")

    def test_persists_to_disk(self, tmp_path, manager):
        manager.create_key("laptop")
        fresh = ApiKeyManager(keys_file=str(tmp_path / "mcp_keys.json"))
        assert len(fresh.list_keys()) == 1


class TestAuthenticate:
    def test_authenticates_with_full_key(self, manager):
        created = manager.create_key("laptop")
        record = manager.authenticate(created["key"])
        assert record is not None
        assert record["name"] == "laptop"

    def test_rejects_garbage(self, manager):
        manager.create_key("laptop")
        assert manager.authenticate("jsort_wrong") is None
        assert manager.authenticate("") is None
        assert manager.authenticate(None) is None

    def test_disabled_key_is_rejected(self, manager):
        created = manager.create_key("laptop")
        assert manager.set_enabled(created["id"], False) is True
        assert manager.authenticate(created["key"]) is None
        assert manager.set_enabled(created["id"], True) is True
        assert manager.authenticate(created["key"]) is not None

    def test_authenticate_records_last_used(self, manager):
        created = manager.create_key("laptop")
        assert manager.authenticate(created["key"]) is not None
        record = manager.authenticate(created["key"])
        assert record["last_used_at"] is not None


class TestLifecycle:
    def test_set_enabled_missing_key(self, manager):
        assert manager.set_enabled("k_missing", True) is False

    def test_delete_key(self, manager):
        created = manager.create_key("laptop")
        assert manager.delete_key(created["id"]) is True
        assert manager.list_keys() == []
        assert manager.delete_key(created["id"]) is False
