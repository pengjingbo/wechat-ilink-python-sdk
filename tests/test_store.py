"""Store module tests for context token persistence and concurrency."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ilink.store import ContextTokenStore, default_token_store


@pytest.fixture()
def tmp_state_dir(tmp_path: Path) -> Path:
    """Provide an isolated temporary state directory for each test."""
    state_dir = tmp_path / "ilink-test-state"
    state_dir.mkdir()
    return state_dir


class TestContextTokenStore:
    """Tests for ContextTokenStore disk persistence."""

    def test_set_writes_to_disk_immediately(self, tmp_state_dir: Path) -> None:
        """set() should flush the latest token mapping to disk immediately."""
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.set("user-1", "token-abc")

        raw = (tmp_state_dir / "context-tokens.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data == {"user-1": "token-abc"}

    def test_get_returns_correct_user_token(self, tmp_state_dir: Path) -> None:
        """get() should return the matching token for each user."""
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.set("user-1", "t1")
        store.set("user-2", "t2")

        assert store.get("user-1") == "t1"
        assert store.get("user-2") == "t2"
        assert store.get("user-unknown") is None

    def test_load_restores_from_disk(self, tmp_state_dir: Path) -> None:
        """load() should restore the token cache from disk."""
        (tmp_state_dir / "context-tokens.json").write_text(
            json.dumps({"u1": "tok1"}), encoding="utf-8"
        )
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.load()

        assert store.get("u1") == "tok1"

    def test_load_missing_file_sets_empty(self, tmp_state_dir: Path) -> None:
        """load() should leave the cache empty when no state file exists."""
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.load()

        assert store.get("any-user") is None


class TestContextTokenStoreConcurrency:
    """Tests for ContextTokenStore thread safety."""

    def test_sync_set_no_deadlock(self, tmp_state_dir: Path) -> None:
        """A single set() call should not deadlock."""
        store = ContextTokenStore(state_dir=tmp_state_dir)
        store.set("u1", "tok1")

        assert store.get("u1") == "tok1"

    def test_sync_concurrent_set_from_multiple_threads(
        self, tmp_state_dir: Path
    ) -> None:
        """Concurrent set() calls should complete without dropping all data."""
        store = ContextTokenStore(state_dir=tmp_state_dir)
        errors: list[Exception] = []

        def writer(tid: int) -> None:
            for i in range(100):
                try:
                    store.set(f"user-{tid}", f"tok-{tid}-{i}")
                except Exception as exc:
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(n,)) for n in range(5)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5.0)

        assert not errors
        for n in range(5):
            assert store.get(f"user-{n}") is not None


class TestModuleSingletons:
    """Tests for module-level singleton exports."""

    def test_token_store_is_context_token_store(self) -> None:
        """default_token_store should remain a ContextTokenStore instance."""
        assert isinstance(default_token_store, ContextTokenStore)
