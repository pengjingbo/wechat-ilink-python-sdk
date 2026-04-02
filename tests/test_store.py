"""store 模块测试：同步刷盘功能 + 并发安全。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ilink.store import (
    ContextTokenStore,
    SyncBufStore,
    default_sync_buf_store,
    default_token_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_state_dir(tmp_path: Path) -> Path:
    """为每个测试提供一个隔离的临时状态目录。"""
    state_dir = tmp_path / "ilink-test-state"
    state_dir.mkdir()
    return state_dir


# ===========================================================================
# SyncBufStore — 同步刷盘功能测试
# ===========================================================================


class TestSyncBufStore:
    """SyncBufStore：set 后数据立即落盘。"""

    def test_set_writes_to_disk_immediately(self, tmp_state_dir: Path) -> None:
        store = SyncBufStore(state_dir=tmp_state_dir)
        store.set("cursor-abc")

        disk_content = (tmp_state_dir / "sync-buf.txt").read_text(encoding="utf-8")
        assert disk_content == "cursor-abc"

    def test_get_returns_latest_value(self, tmp_state_dir: Path) -> None:
        store = SyncBufStore(state_dir=tmp_state_dir)
        store.set("v1")
        store.set("v2")
        assert store.get() == "v2"

    def test_load_restores_from_disk(self, tmp_state_dir: Path) -> None:
        (tmp_state_dir / "sync-buf.txt").write_text("saved-cursor", encoding="utf-8")
        store = SyncBufStore(state_dir=tmp_state_dir)
        store.load()
        assert store.get() == "saved-cursor"

    def test_load_missing_file_sets_empty(self, tmp_state_dir: Path) -> None:
        store = SyncBufStore(state_dir=tmp_state_dir)
        store.load()
        assert store.get() == ""


# ===========================================================================
# ContextTokenStore — 同步刷盘功能测试
# ===========================================================================


class TestContextTokenStore:
    """ContextTokenStore：set 后数据立即落盘。"""

    def test_set_writes_to_disk_immediately(self, tmp_state_dir: Path) -> None:
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.set("user-1", "token-abc")

        raw = (tmp_state_dir / "context-tokens.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data == {"user-1": "token-abc"}

    def test_get_returns_correct_user_token(self, tmp_state_dir: Path) -> None:
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.set("user-1", "t1")
        store.set("user-2", "t2")
        assert store.get("user-1") == "t1"
        assert store.get("user-2") == "t2"
        assert store.get("user-unknown") is None

    def test_load_restores_from_disk(self, tmp_state_dir: Path) -> None:
        (tmp_state_dir / "context-tokens.json").write_text(
            json.dumps({"u1": "tok1"}), encoding="utf-8"
        )
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.load()
        assert store.get("u1") == "tok1"

    def test_load_missing_file_sets_empty(self, tmp_state_dir: Path) -> None:
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.load()
        assert store.get("any-user") is None


# ===========================================================================
# 并发场景测试：多线程 set() 安全
# ===========================================================================


class TestSyncBufStoreConcurrency:
    """SYNC 策略下的并发安全。"""

    def test_sync_set_no_deadlock(self, tmp_state_dir: Path) -> None:
        """set() 不死锁。"""
        store = SyncBufStore(state_dir=tmp_state_dir)
        store.set("should-not-deadlock")
        assert store.get() == "should-not-deadlock"

    def test_sync_concurrent_set_from_multiple_threads(
        self, tmp_state_dir: Path
    ) -> None:
        """多线程并发 set 不死锁、数据不丢失。"""
        store = SyncBufStore(state_dir=tmp_state_dir)
        errors: list[Exception] = []

        def writer(prefix: str) -> None:
            for i in range(100):
                try:
                    store.set(f"{prefix}-{i}")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(f"t{n}",))
            for n in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors
        # 最终值应该是某个线程写入的合法值
        final = store.get()
        assert final.startswith("t")


class TestContextTokenStoreConcurrency:
    """SYNC 策略下 ContextTokenStore 的并发安全。"""

    def test_sync_set_no_deadlock(self, tmp_state_dir: Path) -> None:
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.set("u1", "tok1")
        assert store.get("u1") == "tok1"

    def test_sync_concurrent_set_from_multiple_threads(
        self, tmp_state_dir: Path
    ) -> None:
        store = ContextTokenStore(state_dir=tmp_state_dir)
        errors: list[Exception] = []

        def writer(tid: int) -> None:
            for i in range(100):
                try:
                    store.set(f"user-{tid}", f"tok-{tid}-{i}")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(n,)) for n in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors
        # 每个用户都应该有 token
        for n in range(5):
            assert store.get(f"user-{n}") is not None


# ===========================================================================
# 公共单例测试
# ===========================================================================


class TestModuleSingletons:
    """验证模块级公共单例的类型。"""

    def test_sync_buf_store_is_sync_buf_store(self) -> None:
        assert isinstance(default_sync_buf_store, SyncBufStore)

    def test_token_store_is_context_token_store(self) -> None:
        assert isinstance(default_token_store, ContextTokenStore)
