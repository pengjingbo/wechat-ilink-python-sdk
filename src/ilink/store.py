"""File-based persistence helpers for bot credentials and context tokens."""

from __future__ import annotations

import json
import platform
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

STATE_DIR: Path = Path.home() / ".ilink-python"


def _ensure_dir(dir_path: Path) -> None:
    """
    Ensure a directory exists.

    Args:
        dir_path (Path): Directory path to create when missing.
    """
    dir_path.mkdir(parents=True, exist_ok=True)


class Credentials(BaseModel):
    """
    Persisted bot login credentials.

    Attributes:
        bot_token: iLink bot token.
        account_id: iLink bot account identifier.
        base_url: Base URL for the iLink API.
        user_id: Optional iLink user id from QR login.
        saved_at: ISO 8601 timestamp of when credentials were saved.
    """

    bot_token: str = Field(description="iLink Bot 认证令牌")
    account_id: str = Field(description="iLink Bot 账户 ID")
    base_url: str = Field(description="iLink API 基础 URL")
    user_id: str | None = Field(
        default=None, description="扫码用户的 iLink user ID"
    )
    saved_at: str | None = Field(
        default=None, description="凭证保存时间 ISO 8601"
    )


def _credentials_path() -> Path:
    """
    Return the credentials file path.

    Returns:
        Path: Absolute path to `credentials.json`.
    """
    return STATE_DIR / "credentials.json"


def save_credentials(
    bot_token: str,
    account_id: str,
    base_url: str,
    user_id: str | None = None,
) -> None:
    """
    Save credentials to disk.

    Args:
        bot_token (str): iLink bot token.
        account_id (str): iLink bot account id.
        base_url (str): iLink API base URL.
        user_id (str | None): Optional iLink user id from QR login.
    """
    _ensure_dir(STATE_DIR)
    creds = Credentials(
        bot_token=bot_token,
        account_id=account_id,
        base_url=base_url,
        user_id=user_id,
        saved_at=datetime.now().astimezone().isoformat(),
    )
    path = _credentials_path()
    path.write_text(creds.model_dump_json(indent=2), encoding="utf-8")

    if platform.system() != "Windows":
        path.chmod(0o600)


def load_credentials() -> Credentials | None:
    """
    Load credentials from disk.

    Returns:
        Credentials | None: Parsed credentials, or `None` when the file is
            missing or invalid.
    """
    path = _credentials_path()
    try:
        raw = path.read_text(encoding="utf-8")
        return Credentials.model_validate_json(raw)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


class ContextTokenStore:
    """
    Persistent per-user `context_token` cache.

    Tokens are stored in memory and flushed to disk on every `set()` call.
    """

    _state_dir: Path
    _cache: dict[str, str]
    _lock: threading.Lock

    def __init__(self, state_dir: Path | None = None) -> None:
        """
        Initialize the context token store.

        Args:
            state_dir (Path | None): Optional state directory override.
        """
        self._state_dir = state_dir or STATE_DIR
        self._cache = {}
        self._lock = threading.Lock()

    def _tokens_path(self) -> Path:
        """
        Return the context token file path.

        Returns:
            Path: Absolute path to `context-tokens.json`.
        """
        return self._state_dir / "context-tokens.json"

    def load(self) -> None:
        """
        Load all context tokens from disk into memory.
        """
        try:
            raw = self._tokens_path().read_text(encoding="utf-8")
            data = json.loads(raw)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            data = {}

        with self._lock:
            self._cache = data

    def get(self, user_id: str) -> str | None:
        """
        Return the cached token for a user.

        Args:
            user_id (str): User identifier.

        Returns:
            str | None: Cached token if present, otherwise `None`.
        """
        with self._lock:
            return self._cache.get(user_id)

    def set(self, user_id: str, token: str) -> None:
        """
        Update a user's token and flush the snapshot to disk.

        Args:
            user_id (str): User identifier.
            token (str): Latest context token.
        """
        with self._lock:
            self._cache[user_id] = token
            cache_snapshot = dict(self._cache)

        _ensure_dir(self._state_dir)
        self._tokens_path().write_text(
            json.dumps(cache_snapshot, ensure_ascii=False),
            encoding="utf-8",
        )


default_token_store: ContextTokenStore = ContextTokenStore()
