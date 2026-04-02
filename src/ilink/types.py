"""iLink protocol types — Python port of src/ilink/types.ts.

JSON over HTTP; bytes fields are base64 strings.
All model fields are Optional to match the TypeScript optional (?) semantics.

此模块定义了iLink协议的数据模型和枚举类型，用于微信消息收发SDK。
所有模型基于Pydantic，支持自动类型验证和序列化/反序列化。
注意：所有字段都设置为Optional以匹配TypeScript中的可选字段语义。
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Optional, List  # 显式导入，提高类型提示清晰度

from pydantic import BaseModel, Field  # 添加Field以支持字段描述


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MessageType(IntEnum):
    """消息发送者类型枚举，标识消息的来源"""
    NONE = 0  # 未定义/未知类型
    USER = 1  # 消息来自用户
    BOT = 2   # 消息来自机器人


class MessageItemType(IntEnum):
    """消息内容类型枚举，定义消息项的格式"""
    NONE = 0   # 无内容/未知类型
    TEXT = 1   # 文本消息
    IMAGE = 2  # 图片消息
    VOICE = 3  # 语音消息
    FILE = 4   # 文件消息
    VIDEO = 5  # 视频消息


class MessageState(IntEnum):
    """机器人回复消息的生命周期状态"""
    NEW = 0         # 新消息，未开始处理
    GENERATING = 1  # 正在生成回复
    FINISH = 2      # 消息处理完成


class TypingStatus(IntEnum):
    """输入状态指示器枚举，用于显示"正在输入"状态"""
    TYPING = 1  # 开始显示"正在输入"状态
    CANCEL = 2  # 取消"正在输入"状态


# ---------------------------------------------------------------------------
# Message body models
# ---------------------------------------------------------------------------


class BaseInfo(BaseModel):
    """通道元数据基类，每个API请求都会注入此信息"""
    channel_version: Optional[str] = Field(
        default=None,
        description="通道协议版本号，用于版本兼容性控制"
    )


class TextItem(BaseModel):
    """纯文本内容项模型"""
    text: Optional[str] = Field(
        default=None,
        description="文本内容字符串，支持UTF-8编码"
    )


class VoiceItem(BaseModel):
    """语音内容项模型，包含可选的语音识别转文本"""
    text: Optional[str] = Field(
        default=None,
        description="语音识别(ASR)转换后的文本内容，可能为空"
    )
    encode_type: Optional[int] = Field(
        default=None,
        description="语音编码格式类型标识"
    )
    playtime: Optional[int] = Field(
        default=None,
        description="语音播放时长，单位：毫秒(ms)"
    )


class RefMsg(BaseModel):
    """引用消息模型，用于实现消息引用/回复功能"""
    title: Optional[str] = Field(
        default=None,
        description="引用消息的标题或摘要"
    )
    message_item: Optional['MessageItem'] = Field(
        default=None,
        description="被引用的原始消息项内容"
    )


class MessageItem(BaseModel):
    """消息内容单元模型，是WeixinMessage的组成部分

    表示一个消息中的单个内容块，支持多种类型的内容（文本、图片、语音等）
    """
    type: Optional[int] = Field(
        default=None,
        description="内容类型，对应MessageItemType枚举值"
    )
    text_item: Optional[TextItem] = Field(
        default=None,
        description="文本内容项，当type=TEXT时使用"
    )
    voice_item: Optional[VoiceItem] = Field(
        default=None,
        description="语音内容项，当type=VOICE时使用"
    )
    ref_msg: Optional[RefMsg] = Field(
        default=None,
        description="引用消息项，用于消息回复/引用功能"
    )


class \
        WeixinMessage(BaseModel):
    """微信消息核心模型，表示用户和机器人之间交换的消息

    包含消息的完整元数据和内容，支持单聊和群聊场景
    """
    seq: Optional[int] = Field(
        default=None,
        description="消息序列号，用于消息排序和去重"
    )
    message_id: Optional[int] = Field(
        default=None,
        description="消息唯一标识ID"
    )
    from_user_id: Optional[str] = Field(
        default=None,
        description="发送者用户ID"
    )
    to_user_id: Optional[str] = Field(
        default=None,
        description="接收者用户ID"
    )
    client_id: Optional[str] = Field(
        default=None,
        description="客户端标识，用于多设备登录区分"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="会话ID，标识一次完整的对话流程"
    )
    group_id: Optional[str] = Field(
        default=None,
        description="群组ID，群聊消息时非空"
    )
    message_type: Optional[int] = Field(
        default=None,
        description="消息类型，对应MessageType枚举值"
    )
    message_state: Optional[int] = Field(
        default=None,
        description="消息状态，对应MessageState枚举值"
    )
    item_list: Optional[List[MessageItem]] = Field(
        default=None,
        description="消息内容项列表，支持富媒体消息（文本+图片等组合）"
    )
    context_token: Optional[str] = Field(
        default=None,
        description="上下文令牌，用于关联连续对话"
    )
    create_time_ms: Optional[int] = Field(
        default=None,
        description="消息创建时间戳，单位：毫秒(ms)"
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GetUpdatesReq(BaseModel):
    """获取消息更新请求模型，支持长轮询机制

    用于从服务器拉取新消息，支持断点续传和增量获取
    """
    get_updates_buf: Optional[str] = Field(
        default=None,
        description="增量拉取缓冲区标识，用于实现断点续传功能"
    )


class GetUpdatesResp(BaseModel):
    """获取消息更新响应模型，包含新消息列表"""
    ret: Optional[int] = Field(
        default=None,
        description="返回码，0表示成功，非0表示错误"
    )
    errcode: Optional[int] = Field(
        default=None,
        description="错误代码，更细粒度的错误分类"
    )
    errmsg: Optional[str] = Field(
        default=None,
        description="错误描述信息，用于调试和用户提示"
    )
    msgs: Optional[List[WeixinMessage]] = Field(
        default=None,
        description="新消息列表，可能为空列表表示无新消息"
    )
    get_updates_buf: Optional[str] = Field(
        default=None,
        description="更新后的缓冲区标识，用于下一次增量拉取"
    )
    longpolling_timeout_ms: Optional[int] = Field(
        default=None,
        description="长轮询超时时间建议值，单位：毫秒(ms)"
    )


class SendMessageReq(BaseModel):
    """发送消息请求模型，将机器人回复发送给用户"""
    msg: Optional[WeixinMessage] = Field(
        default=None,
        description="要发送的微信消息对象"
    )


class GetConfigResp(BaseModel):
    """获取机器人配置响应模型"""
    ret: Optional[int] = Field(
        default=None,
        description="返回码，0表示成功"
    )
    errmsg: Optional[str] = Field(
        default=None,
        description="错误信息，成功时通常为空"
    )
    typing_ticket: Optional[str] = Field(
        default=None,
        description="输入状态票据，用于发送\"正在输入\"状态指示"
    )


class SendTypingReq(BaseModel):
    """发送输入状态请求模型，控制"正在输入"指示器的显示"""
    ilink_user_id: Optional[str] = Field(
        default=None,
        description="iLink用户ID，标识目标用户"
    )
    typing_ticket: Optional[str] = Field(
        default=None,
        description="输入状态票据，从GetConfigResp获取"
    )
    status: Optional[int] = Field(
        default=None,
        description="输入状态，对应TypingStatus枚举值"
    )


# ---------------------------------------------------------------------------
# API options
# ---------------------------------------------------------------------------


class ApiOptions(BaseModel):
    """iLink HTTP API连接配置模型

    用于配置SDK与iLink服务器通信的基本参数
    """
    base_url: str = Field(
        description="iLink API服务器的基础URL，例如: https://api.example.com/v1"
    )
    token: str = Field(
        description="身份验证令牌，用于API请求鉴权",
        min_length=1
    )


# 解析前向引用（解决RefMsg和MessageItem之间的循环引用）
# 在Pydantic V2中，需要使用model_rebuild()来处理前向引用
RefMsg.model_rebuild()


# ---------------------------------------------------------------------------
# Auth constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
QR_POLL_TIMEOUT_S = 35.0
LOGIN_TIMEOUT_S = 480.0  # 8 minutes, matching iLink design
MAX_QR_REFRESH = 3


# ---------------------------------------------------------------------------
# Auth enumerations
# ---------------------------------------------------------------------------


class QRStatus(StrEnum):
    """QR code polling status values."""

    WAIT = "wait"
    SCANNED = "scaned"  # 保持与 iLink 服务端原始拼写一致
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Auth data models
# ---------------------------------------------------------------------------


class LoginResult(BaseModel):
    """Credentials returned after a successful QR login."""

    bot_token: str
    account_id: str  # ilink_bot_id
    base_url: str
    user_id: str | None = None  # ilink_user_id of the scanner


class QRCodeResponse(BaseModel):
    """Response from GET get_bot_qrcode."""

    qrcode: str
    qrcode_img_content: str


class StatusResponse(BaseModel):
    """Response from GET get_qrcode_status."""

    status: QRStatus
    bot_token: str | None = None
    ilink_bot_id: str | None = None
    baseurl: str | None = None
    ilink_user_id: str | None = None
