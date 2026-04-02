"""Simple file-based persistence for bot credentials and state.

Stores data in ~/.ilink-python/ directory. Provides:
- Credentials save/load (credentials.json)
- Sync buffer cursor persistence (sync-buf.txt)
- Per-user context token cache (context-tokens.json)

All writes are synchronous: every set() immediately flushes to disk.

对应 TypeScript 源文件: src/store.ts
"""

from __future__ import annotations

import json
import platform
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

STATE_DIR: Path = Path.home() / ".ilink-python"


def _ensure_dir(dir_path: Path) -> None:
    """确保目录存在，不存在则递归创建。

    Args:
        dir_path (Path): 需要确保存在的目录路径。
    """
    dir_path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class Credentials(BaseModel):
    """Bot 登录凭证，JSON 序列化后存储到 credentials.json。"""

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
    """获取凭证文件路径。

    Returns:
        Path: credentials.json 的完整路径。
    """
    return STATE_DIR / "credentials.json"


def save_credentials(
    bot_token: str,
    account_id: str,
    base_url: str,
    user_id: str | None = None,
) -> None:
    """将凭证写入磁盘。Linux/Mac 下设置文件权限为 0o600。

    Args:
        bot_token (str): iLink Bot 认证令牌。
        account_id (str): iLink Bot 账户 ID。
        base_url (str): iLink API 基础 URL。
        user_id (str | None): 扫码用户的 iLink user ID，可选。
    """
    _ensure_dir(STATE_DIR)
    creds: Credentials = Credentials(
        bot_token=bot_token,
        account_id=account_id,
        base_url=base_url,
        user_id=user_id,
        saved_at=datetime.now().astimezone().isoformat(),
    )
    path: Path = _credentials_path()
    path.write_text(creds.model_dump_json(indent=2), encoding="utf-8")

    if platform.system() != "Windows":
        path.chmod(0o600)


def load_credentials() -> Credentials | None:
    """从磁盘加载凭证。文件不存在或解析失败返回 None。

    Returns:
        Credentials | None: Credentials 实例，或文件不存在/损坏时返回 None。
    """
    path: Path = _credentials_path()
    try:
        raw: str = path.read_text(encoding="utf-8")
        return Credentials.model_validate_json(raw)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# SyncBufStore (getUpdates cursor)
# ---------------------------------------------------------------------------


class SyncBufStore:
    """getUpdates 同步游标的持久化管理器。

    每次 set() 立即将数据同步写入磁盘，确保数据安全。
    """

    _state_dir: Path  # 状态文件存储目录
    _buf: str  # 内存中的 sync buffer 值
    _lock: threading.Lock  # 保护 _buf 的线程锁

    def __init__(
        self,
        state_dir: Path | None = None,
    ) -> None:
        """初始化 SyncBufStore。

        Args:
            state_dir (Path | None): 状态存储目录，默认为 STATE_DIR。
        """
        self._state_dir = state_dir or STATE_DIR
        self._buf = ""
        self._lock = threading.Lock()

    def _file_path(self) -> Path:
        """获取同步游标文件路径。

        Returns:
            Path: sync-buf.txt 的完整路径。
        """
        return self._state_dir / "sync-buf.txt"

    def load(self) -> None:
        """从磁盘加载 sync buffer 到内存。注：只有当程序崩溃的时候才需要执行 load()。"""
        try:
            raw: str = self._file_path().read_text(encoding="utf-8")
            with self._lock:
                self._buf = raw
        except FileNotFoundError:
            self._buf = ""

    def get(self) -> str:
        """获取当前 sync buffer 值。

        Returns:
            str: 当前的 sync buffer 字符串。
        """
        with self._lock:
            return self._buf

    def set(self, buf: str) -> None:
        """设置 sync buffer 值并立即写入磁盘。

        Args:
            buf (str): 新的 sync buffer 值。
        """
        with self._lock:
            self._buf = buf
            buf_snapshot = self._buf

        _ensure_dir(self._state_dir)
        self._file_path().write_text(buf_snapshot, encoding="utf-8")


# ---------------------------------------------------------------------------
# ContextTokenStore (per-user)
# ---------------------------------------------------------------------------


class ContextTokenStore:
    """Per-user context_token 的内存缓存 + 磁盘持久化管理器。

    context_token 用于关联连续对话，每个用户维护独立的令牌。
    每次 set() 立即将数据同步写入磁盘，确保数据安全。
    """

    _state_dir: Path  # 状态文件存储目录
    _cache: dict[str, str]  # 内存缓存，user_id -> context_token 映射
    _lock: threading.Lock  # 保护 _cache 的线程锁

    def __init__(
        self,
        state_dir: Path | None = None,
    ) -> None:
        """初始化 ContextTokenStore。

        Args:
            state_dir (Path | None): 状态存储目录，默认为 STATE_DIR。
        """
        self._state_dir = state_dir or STATE_DIR
        self._cache = {}
        self._lock = threading.Lock()

    def _tokens_path(self) -> Path:
        """获取 context tokens 文件路径。

        Returns:
            Path: context-tokens.json 的完整路径。
        """
        return self._state_dir / "context-tokens.json"

    def load(self) -> None:
        """从磁盘加载所有 context token 到内存缓存。注：只有当程序崩溃的时候才需要执行 load()。"""
        try:
            raw: str = self._tokens_path().read_text(encoding="utf-8")
            with self._lock:
                self._cache = json.loads(raw)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            self._cache = {}

    def get(self, user_id: str) -> str | None:
        """获取指定用户的 context token。

        Args:
            user_id (str): 用户 ID。

        Returns:
            str | None: 用户的 context token，未找到返回 None。
        """
        with self._lock:
            return self._cache.get(user_id)

    def set(self, user_id: str, token: str) -> None:
        """设置指定用户的 context token 并立即写入磁盘。

        Args:
            user_id (str): 用户 ID。
            token (str): 新的 context token 值。
        """
        with self._lock:
            self._cache[user_id] = token
            cache_snapshot = dict(self._cache)

        _ensure_dir(self._state_dir)
        self._tokens_path().write_text(
            json.dumps(cache_snapshot, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Module-level convenience (singletons)
# ---------------------------------------------------------------------------

default_sync_buf_store: SyncBufStore = SyncBufStore()
default_token_store: ContextTokenStore = ContextTokenStore()
