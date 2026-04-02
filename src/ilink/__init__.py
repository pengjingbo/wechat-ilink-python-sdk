"""Public package exports for the iLink SDK."""

from .auth import login_with_qr
from .client import (
    CHANNEL_VERSION,
    DEFAULT_API_TIMEOUT_S,
    DEFAULT_LONG_POLL_TIMEOUT_S,
    ILinkClient,
    ILinkError,
    OnMessageCallback,
    PollError,
    SessionExpiredError,
)
from .store import (
    ContextTokenStore,
    Credentials,
    default_token_store,
    load_credentials,
    save_credentials,
)
from .types import LoginResult, QRCodeResponse, QRStatus, StatusResponse
from .utils import (
    MAX_MSG_LEN,
    build_headers,
    generate_client_id,
    random_wechat_uin,
)

__all__ = [
    # auth
    "login_with_qr",
    # client
    "CHANNEL_VERSION",
    "DEFAULT_API_TIMEOUT_S",
    "DEFAULT_LONG_POLL_TIMEOUT_S",
    "ILinkClient",
    "ILinkError",
    "OnMessageCallback",
    "PollError",
    "SessionExpiredError",
    # store — models & classes
    "ContextTokenStore",
    "Credentials",
    # store — public singletons
    "default_token_store",
    # store — functions
    "load_credentials",
    "save_credentials",
    # types
    "LoginResult",
    "QRCodeResponse",
    "QRStatus",
    "StatusResponse",
    # utils
    "MAX_MSG_LEN",
    "build_headers",
    "generate_client_id",
    "random_wechat_uin",
]
