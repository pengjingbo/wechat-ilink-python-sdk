"""iLink HTTP 客户端 — 异步 API 封装 + 长轮询消息循环。

本模块是 iLink SDK 的核心模块，提供与 iLink 服务器通信的完整能力：
- HTTP API 封装：get_updates、send_message、send_typing、get_config
- 消息处理工具：文本提取、长消息分片回复、输入状态指示
- 长轮询循环：持续拉取新消息并分发给业务回调

"""

from __future__ import annotations

# stdlib
import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable

# third-party
import httpx

# local
from .store import (
    ContextTokenStore,
    SyncBufStore,
    default_sync_buf_store,
    default_token_store,
)
from .types import (
    ApiOptions,
    GetConfigResp,
    GetUpdatesResp,
    MessageItem,
    MessageItemType,
    MessageState,
    MessageType,
    TextItem,
    TypingStatus,
    WeixinMessage,
)
from .utils import MAX_MSG_LEN, build_headers, generate_client_id

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块常量（移植自 api.ts）
# ---------------------------------------------------------------------------

# 通道版本号，注入到每个 API 请求的 base_info 中，用于服务端识别客户端版本
CHANNEL_VERSION: str = "weixin-claude-bot/0.1.0"

# 长轮询默认超时（秒）。iLink 服务端长轮询超时约 30s，客户端设置 35s 留 5s 余量
DEFAULT_LONG_POLL_TIMEOUT_S: float = 35.0

# 普通 API 调用默认超时（秒）。send_message / get_config 等短请求使用
DEFAULT_API_TIMEOUT_S: float = 15.0

# iLink 返回此错误码表示 session 已过期，需要重新登录或等待恢复
SESSION_EXPIRED_ERRCODE: int = -14

# 消息回调类型别名：接收 WeixinMessage 参数，返回 awaitable None 的异步回调函数
OnMessageCallback = Callable[[WeixinMessage], Awaitable[None]]


# ---------------------------------------------------------------------------
# 自定义异常类
# ---------------------------------------------------------------------------


class ILinkError(Exception):
    """iLink SDK 异常基类。

    所有 iLink SDK 特定的异常均继承自此类，
    用户可以 ``except ILinkError`` 一次捕获所有 SDK 异常。
    """


class SessionExpiredError(ILinkError):
    """会话过期异常。

    当 iLink 服务端返回 errcode=-14 时抛出。
    调用方应捕获此异常并决定是否重新登录或退出。
    """


class PollError(ILinkError):
    """连续业务错误异常。

    当 getUpdates 返回非零错误码且连续失败达到阈值时抛出。
    携带最后一次错误的 ret 和 errcode，方便调用方诊断。

    Attributes:
        ret: 最后一次错误响应的 ret 值。
        errcode: 最后一次错误响应的 errcode 值。
        consecutive: 连续失败次数。
    """

    def __init__(
        self,
        ret: int | None,
        errcode: int | None,
        consecutive: int,
    ) -> None:
        self.ret = ret
        self.errcode = errcode
        self.consecutive = consecutive
        super().__init__(
            f"getUpdates 连续 {consecutive} 次业务错误 "
            f"(ret={ret}, errcode={errcode})"
        )


class ILinkClient:
    """异步 iLink HTTP 客户端，封装 API 调用与长轮询消息循环。

    典型用法::

        api = ApiOptions(base_url="https://...", token="...")
        client = ILinkClient(api)
        async with client:
            resp = await client.get_updates()
    """

    # 类属性类型声明
    _api: ApiOptions  # iLink API 连接配置（base_url + token）
    _http: httpx.AsyncClient | None  # httpx 异步客户端实例，进入上下文后初始化

    def __init__(self, api: ApiOptions) -> None:
        """初始化 ILinkClient。

        Args:
            api (ApiOptions): iLink API 连接配置，包含 base_url 和 token。
        """
        self._api = api
        # 延迟到 __aenter__ 中创建，确保在事件循环内初始化
        self._http = None

    # -- 异步上下文管理器 --

    async def __aenter__(self) -> ILinkClient:
        """进入异步上下文：创建 httpx.AsyncClient 实例。

        这是异步上下文管理器的入口方法，当使用 `async with ILinkClient(...) as client:` 语法时调用。

        工作原理：
        1. Python 解释器遇到 `async with` 语句时，会自动调用此方法
        2. 在此方法中创建并初始化 httpx 异步客户端
        3. 返回当前实例自身，使其可以在 `as` 子句中被引用

        资源管理：
        - 创建 httpx.AsyncClient 实例，它会自动管理连接池
        - 这个客户端会复用 TCP 连接，提高后续 HTTP 请求的性能
        - 避免了为每个请求创建新连接的开销

        返回值：
            ILinkClient: 当前客户端实例，支持链式调用。
        """
        # 创建 httpx 异步客户端，后续所有 HTTP 请求共享此连接池
        # httpx.AsyncClient 会自动管理连接池、keep-alive、连接复用等
        # 使用连接池可以显著提高性能，特别是在频繁发送 HTTP 请求的场景
        self._http = httpx.AsyncClient()

        # 返回当前实例，这样在 async with 块中可以使用这个实例
        # 例如：async with ILinkClient() as client: 中的 client 就是这里返回的实例
        return self

    async def __aexit__(self, *exc: object) -> None:
        """退出异步上下文：安全关闭 httpx 连接池，释放网络资源。

        这是异步上下文管理器的出口方法，当 `async with` 代码块执行完毕（正常或异常）时调用。

        工作原理：
        1. 无论 async with 代码块是正常结束还是抛出异常，都会调用此方法
        2. 此方法负责清理在 __aenter__ 中创建的资源
        3. 参数 *exc 包含异常信息（如果有异常发生）

        资源清理：
        - 调用 httpx.AsyncClient 的 aclose() 方法优雅关闭连接池
        - 关闭所有保持活动的连接
        - 取消所有待处理的请求
        - 释放所有相关资源

        异常处理：
        - 如果 async with 块中发生异常，异常信息会通过 *exc 参数传递
        - 但此方法不处理异常，只是确保资源被正确清理
        - 清理完成后，异常会继续向上传播（除非在此方法中捕获并处理）

        注意：
        - 必须使用 await 调用 aclose()，因为它是异步方法
        - 将 _http 设为 None 避免悬空引用
        - 即使关闭过程中发生异常，也应确保 _http 被设为 None
        """
        if self._http is not None:
            # 异步关闭 httpx 客户端
            # aclose() 会：
            # 1. 等待所有已发送请求完成
            # 2. 优雅关闭所有连接
            # 3. 释放连接池资源
            # 4. 防止资源泄漏
            await self._http.aclose()

            # 将引用设为 None，避免后续代码错误地使用已关闭的客户端
            # 这也有助于垃圾回收
            self._http = None

    # -- 内部 HTTP 辅助方法 --

    async def _post(
            self,
            endpoint: str,
            payload: dict[str, Any],
            timeout_s: float = DEFAULT_API_TIMEOUT_S,
    ) -> dict[str, Any]:
        """向 iLink API 发送 POST 请求。

        核心功能：向 iLink 服务端发送 HTTP POST 请求，并处理完整的请求-响应生命周期。
        该方法封装了请求构建、错误处理、响应解析等细节，是客户端与 iLink 服务端通信的主要桥梁。

        请求处理流程：
        1. 检查客户端状态（必须在 async with 上下文内）
        2. 拼接完整 API 请求 URL
        3. 向请求体注入必要的元信息（如通道版本）
        4. 序列化请求体为 JSON 字符串
        5. 构建包含认证信息的 HTTP 头部
        6. 发送异步 HTTP 请求
        7. 检查响应状态码
        8. 解析 JSON 响应

        自动向 payload 注入 ``base_info.channel_version`` 字段，
        并构建包含认证信息的请求头。

        Args:
            endpoint (str): API 相对路径，例如 ``"ilink/bot/sendmessage"``。
                注意：endpoint 应该是不包含 base_url 的相对路径，方法会自动与配置的基础 URL 拼接。
            payload (dict[str, Any]): JSON 可序列化的请求体。
                这个字典包含了业务逻辑需要的所有数据，方法会自动注入必要的元信息字段。
            timeout_s (float): 请求超时时间（秒），默认 15s。
                超时时间从连接建立开始计算，包括请求发送、服务端处理和响应接收的全过程。

        Returns:
            dict[str, Any]: 解析后的 JSON 响应字典。
            返回的是服务端响应的完整 JSON 数据，通常包含状态码、消息内容等信息。

        Raises:
            RuntimeError: 在 ``async with`` 上下文外调用时抛出。
                这表示客户端未正确初始化，通常是因为没有使用 `async with ILinkClient() as client:` 语法。
            httpx.HTTPStatusError: 服务端返回非 2xx 状态码。
                表示 HTTP 请求成功发送但服务端返回了错误状态（如 400 Bad Request, 500 Internal Server Error）。
            httpx.TimeoutException: 请求超时。
                表示在指定时间内未收到服务端响应，可能是网络问题或服务端处理过慢。
            httpx.RequestError: 其他网络请求错误。
                如网络不可达、DNS解析失败、连接被拒绝等。
            json.JSONDecodeError: 响应体不是有效的 JSON 格式。
                服务端返回了非 JSON 格式的响应内容。
        """
        # 前置检查：确保已进入异步上下文管理器
        # 这是安全防护，防止在 _http 客户端未初始化的情况下发送请求
        if self._http is None:
            raise RuntimeError(
                "ILinkClient must be used as an async context manager. "
                "请使用 'async with ILinkClient(...) as client:' 语法。"
            )

        # 步骤 1：拼接完整 URL
        # 去除 base_url 末尾可能存在的斜杠，然后添加一个斜杠，再追加 endpoint
        # 确保最终 URL 格式正确，如 "https://api.example.com/v1/ilink/bot/sendmessage"
        base: str = self._api.base_url.rstrip("/") + "/"
        url: str = base + endpoint

        # 步骤 2：向 payload 注入通道版本号
        # 创建一个新的字典，包含原始 payload 的所有键值对
        # 并添加 base_info.channel_version 字段，用于服务端识别客户端版本
        # 这是 iLink API 的协议要求，服务端根据此字段做版本兼容性处理
        body_dict: dict[str, Any] = {
            **payload,  # 展开原始 payload
            "base_info": {"channel_version": CHANNEL_VERSION},
        }

        # 步骤 3：序列化为 JSON 字符串
        # 将字典序列化为 JSON 格式的字符串
        # ensure_ascii=False 确保中文字符等 Unicode 字符保持原样，而不是转义为 \u 格式
        # 这使请求体更易读，但体积可能稍大（对 ASCII 字符无影响）
        body: str = json.dumps(body_dict, ensure_ascii=False)

        # 步骤 4：构建 HTTP 请求头
        # 调用 build_headers 函数生成标准的 iLink API 请求头
        # 包括：
        #   - Content-Type: application/json
        #   - Authorization: Bearer {token}
        #   - AuthorizationType: ilink_bot_token
        #   - Content-Length: 请求体字节长度
        #   - X-WECHAT-UIN: 随机的微信 UIN
        headers: dict[str, str] = build_headers(self._api.token, body)

        # 步骤 5：发送 POST 请求
        # 使用 httpx.AsyncClient 发送异步 POST 请求
        # 参数说明：
        #   - url: 完整的 API 地址
        #   - content=body.encode("utf-8"): 明确使用 UTF-8 编码的字节串作为请求体
        #     这比传递字符串更高效，避免了 httpx 内部再次编码
        #   - headers: 前面构建的请求头字典
        #   - timeout=timeout_s: 超时时间设置
        # 注意：这里使用 await 异步等待请求完成，期间可以切换执行其他协程
        response: httpx.Response = await self._http.post(
            url,
            content=body.encode("utf-8"),  # 显式指定编码，避免编码歧义
            headers=headers,
            timeout=timeout_s,
        )

        # 步骤 6：检查 HTTP 状态码
        # 调用 raise_for_status() 方法，如果状态码不是 2xx，则抛出 httpx.HTTPStatusError
        # 这是最佳实践，尽早发现并处理错误响应
        # 注意：此方法不会检查业务逻辑错误，只检查 HTTP 协议层面的错误
        response.raise_for_status()

        # 步骤 7：解析并返回 JSON 响应
        # 将响应体解析为 Python 字典
        # response.json() 会自动处理 JSON 反序列化，并根据 Content-Type 选择编码
        # 如果响应体不是有效 JSON，会抛出 json.JSONDecodeError
        return response.json()
    # -- 公共 API 方法（移植自 api.ts） --

    async def get_updates(
            self,
            sync_buf: str = "",
    ) -> GetUpdatesResp:
        """长轮询拉取新消息。

        核心功能：向 iLink 服务端发送长轮询请求，拉取新到达的消息。
        该方法实现了"长轮询"（Long Polling）机制，是实时消息推送的替代方案。

        工作原理：
        1. 客户端发送请求到服务端，请求中携带当前同步游标（sync_buf）
        2. 服务端检查是否有新消息：
           a. 如果立即有消息，立即返回消息列表
           b. 如果当前没有消息，服务端会"挂起"请求，等待新消息到达
        3. 两种情况结束请求：
           a. 等待期间有新消息到达 -> 立即返回消息
           b. 等待超时（35秒）-> 返回空响应
        4. 客户端收到响应后，立即发起下一个长轮询请求

        使用 35s 超时进行长轮询，服务端有新消息时立即返回，
        无新消息时等待至超时。客户端超时时返回空结果而非抛出异常，
        实现优雅降级。

        长轮询 vs 短轮询：
        - 短轮询：客户端频繁发送请求（如每秒一次），无论是否有消息都立即返回
        - 长轮询：客户端发送请求后，服务端保持连接直到有消息或超时
        - 优势：减少无效请求，降低服务器压力，提高消息实时性

        Args:
            sync_buf (str): 上一次响应返回的同步游标，用于增量拉取。
                这个字符串是服务端返回的不透明标记，用于：
                1. 标识客户端已经处理到的消息位置
                2. 服务端根据此游标只返回更新（增量）的消息
                3. 确保消息不会丢失或重复
                首次调用时传入空字符串，后续使用上次响应中的 get_updates_buf 值。

        Returns:
            GetUpdatesResp: 包含新消息列表和更新后游标的响应对象。
            响应对象通常包含以下字段：
            - ret: 返回码（0表示成功）
            - msgs: 新消息列表，如果没有新消息则为空列表
            - get_updates_buf: 新的同步游标，用于下一次调用

        """
        try:
            # 使用长轮询超时调用 getupdates 接口
            # 调用 _post 方法发送 POST 请求到 ilink/bot/getupdates 端点
            # 请求体包含 get_updates_buf 字段，携带当前同步游标
            # timeout_s 设置为 35 秒，这是长轮询的标准超时时间
            data: dict[str, Any] = await self._post(
                "ilink/bot/getupdates",  # API 端点路径
                {"get_updates_buf": sync_buf},  # 请求体，包含同步游标
                timeout_s=DEFAULT_LONG_POLL_TIMEOUT_S,  # 长轮询超时时间（35秒）
            )

            # 将响应数据解析为 GetUpdatesResp 对象
            # 使用 Pydantic 的 model_validate 进行数据验证和类型转换
            # 这确保了响应数据的结构符合预期，提供了类型安全
            return GetUpdatesResp.model_validate(data)

        except httpx.TimeoutException:
            # 超时降级：返回空消息列表，保留当前游标，不中断轮询循环
            # 长轮询超时是正常情况，表示在35秒内没有新消息到达
            # 返回一个有效的 GetUpdatesResp 对象，但 msgs 字段为空列表
            # 保持 sync_buf 不变，下次请求继续使用相同的游标
            return GetUpdatesResp(
                ret=0,  # 返回码0表示成功（尽管没有新消息）
                msgs=[],  # 空消息列表
                get_updates_buf=sync_buf,  # 同步游标保持不变
            )

    async def send_message(self, msg: WeixinMessage) -> None:
        """发送消息给用户。

        核心功能：将微信消息对象发送给指定用户或群组。
        这是 ILinkClient 的主要业务方法，用于实现机器人消息发送功能。

        工作原理：
        1. 接收一个结构化的微信消息对象（WeixinMessage）
        2. 将消息对象转换为符合 iLink API 协议的字典格式
        3. 通过 HTTP POST 请求将消息发送到 iLink 服务端
        4. iLink 服务端将消息转发到微信客户端

        将 WeixinMessage 序列化后通过 sendmessage 接口发送，
        自动排除值为 None 的字段以减小请求体积。

        支持的消息类型（通过 WeixinMessage.msg_type 区分）：
        - 文本消息 (text)
        - 图片消息 (image)
        - 语音消息 (voice)
        - 视频消息 (video)
        - 文件消息 (file)
        - 文本卡片消息 (textcard)
        - 图文消息 (news)
        - Markdown 消息 (markdown)

        Args:
            msg (WeixinMessage): 待发送的消息对象。
                这是一个 Pydantic 模型，包含以下关键字段：
                - msg_type: 消息类型，如 "text"、"image" 等
                - to_user: 接收者用户ID，可以是单个用户或用户列表
                - content: 消息内容，根据消息类型不同而结构不同
                - agent_id: 应用代理ID（企业微信中用到）
                - safe: 是否是保密消息

        Returns:
            None: 该方法不返回任何值，发送成功时静默完成，失败时抛出异常。

        Raises:
            httpx.HTTPStatusError: 当 iLink 服务端返回非 2xx 状态码时抛出
            httpx.TimeoutException: 当请求超时时抛出
            httpx.RequestError: 当网络请求失败时抛出
            RuntimeError: 当在 async with 上下文外调用时抛出

        示例:
            # 创建文本消息
            text_msg = WeixinMessage(
                msg_type="text",
                to_user="user123",
                content={"text": "你好，这是测试消息"}
            )

            # 发送消息
            async with ILinkClient(token="your_token", base_url="...") as client:
                await client.send_message(text_msg)
        """
        # 调用 _post 方法发送 HTTP 请求
        # 第一个参数是 API 端点路径 "ilink/bot/sendmessage"
        # 第二个参数是请求体，将消息对象序列化为字典
        await self._post(
            "ilink/bot/sendmessage",  # iLink 消息发送接口路径
            # 请求体结构：{"msg": {消息数据字典}}
            # 使用 msg.model_dump(exclude_none=True) 序列化消息对象
            # exclude_none=True 的作用：
            # 1. 只序列化非 None 值的字段，减少请求体大小
            # 2. 避免发送无意义的数据，提高传输效率
            # 3. 符合 iLink 协议要求，服务端不期望收到 None 值字段
            {"msg": msg.model_dump(exclude_none=True)},
        )
        # 注意：这里没有返回值，因为消息发送通常只需关注是否成功
        # 如果发送失败，_post 方法会抛出相应的异常
        # 如果发送成功，静默完成，上层可通过 try-except 捕获异常来判断结果

    async def send_typing(
            self,
            user_id: str,
            typing_ticket: str,
            status: TypingStatus = TypingStatus.TYPING,
    ) -> None:
        """发送输入状态指示器（"正在输入..."）。

        核心功能：向指定用户发送"正在输入"状态指示，在聊天界面中显示对方正在输入的效果。
        这是一种用户体验增强功能，模拟真人聊天的交互感，让用户知道机器人正在处理并即将回复。

        工作原理：
        1. 客户端向 iLink 服务端发送用户输入状态请求
        2. 服务端将状态推送到微信客户端
        3. 微信客户端在聊天界面显示"对方正在输入..."提示
        4. 状态持续一段时间后自动消失，或通过发送 CLEAR 状态主动清除

        使用场景：
        - 机器人收到消息后，在处理过程中显示"正在输入"
        - 长时间处理任务时，定期发送 TYPING 状态保持提示
        - 处理完成后发送 CLEAR 状态清除提示
        - 取消回复时发送 CLEAR 状态清除提示

        Args:
            user_id (str): 目标用户的 iLink 用户 ID。
                这是用户的唯一标识符，用于指定显示输入状态的目标用户。
                注意：必须是有效的 iLink 用户 ID，而非微信原生用户 ID。

            typing_ticket (str): 从 get_config 获取的输入状态票据。
                这是一个一次性令牌，用于验证发送输入状态的权限。
                票据通过调用 get_config 接口获得，通常有一定的有效期。
                票据与用户 ID 绑定，不能跨用户使用。

            status (TypingStatus): 输入状态，默认为 TYPING（开始显示）。
                这是一个枚举值，包含两种状态：
                - TYPING: 显示"正在输入"状态
                - CLEAR: 清除"正在输入"状态
                默认值为 TYPING，表示开始显示输入状态。

        注意事项:
        1. 输入状态票据有有效期，过期后需要重新获取
        2. 过于频繁地发送输入状态可能被微信限制
        3. 输入状态不会自动清除，需要手动发送 CLEAR 状态或等待超时自动消失
        4. 企业微信和个人微信对此功能的支持程度可能不同
        5. 输入状态只在双方聊天窗口打开时有效

        最佳实践:
        1. 在开始处理消息时立即发送 TYPING 状态
        2. 如果处理时间超过 15 秒，可以定期重新发送 TYPING 状态保持提示
        3. 处理完成后发送 CLEAR 状态清除提示
        4. 如果处理失败，也应发送 CLEAR 状态避免误导用户
        5. 将票据缓存起来，避免每次发送输入状态都调用 get_config

        示例:
            async def reply_with_typing(client: ILinkClient, user_id: str, question: str):
                # 1. 获取输入状态票据
                config = await client.get_config()
                ticket = config.typing_ticket

                # 2. 发送"正在输入"状态
                await client.send_typing(user_id, ticket, TypingStatus.TYPING)

                try:
                    # 3. 模拟处理过程
                    await asyncio.sleep(2)  # 模拟耗时处理

                    # 4. 生成回复
                    reply = await generate_reply(question)

                    # 5. 清除输入状态
                    await client.send_typing(user_id, ticket, TypingStatus.CLEAR)

                    # 6. 发送实际回复
                    msg = WeixinMessage(
                        msg_type="text",
                        to_user=user_id,
                        content={"text": reply}
                    )
                    await client.send_message(msg)

                except Exception as e:
                    # 处理失败时也要清除输入状态
                    await client.send_typing(user_id, ticket, TypingStatus.CLEAR)
                    raise
        """
        # 调用 _post 方法发送 HTTP 请求
        # 第一个参数是 API 端点路径 "ilink/bot/sendtyping"
        # 第二个参数是请求体，包含发送输入状态所需的三个参数
        await self._post(
            "ilink/bot/sendtyping",  # iLink 输入状态发送接口路径
            # 请求体结构，包含三个必需字段：
            {
                "ilink_user_id": user_id,  # 目标用户的 iLink 用户 ID
                "typing_ticket": typing_ticket,  # 输入状态票据，从 get_config 获取
                "status": status,  # 输入状态：TYPING 或 CLEAR
            },
        )
        # 注意：这里没有返回值，因为输入状态发送通常只需关注是否成功
        # 如果发送失败，_post 方法会抛出相应的异常
        # 如果发送成功，静默完成，上层可通过 try-except 捕获异常来判断结果

    async def get_config(
            self,
            user_id: str,
            context_token: str | None = None,
    ) -> GetConfigResp:
        """获取机器人配置信息（typing_ticket 等）。

        核心功能：获取指定用户的 iLink 机器人配置信息，特别是用于发送输入状态（"正在输入..."）的票据。
        这个方法通常在机器人需要与特定用户进行交互前调用，以获取必要的认证令牌和配置参数。

        主要用途：
        1. 获取 typing_ticket，用于后续调用 send_typing 方法显示输入状态
        2. 获取其他可能的机器人配置信息（如权限、功能开关等）
        3. 验证用户身份和机器人权限
        4. 建立或更新对话上下文

        工作原理：
        1. 向 iLink 服务端发送请求，携带目标用户 ID 和可选的上下文令牌
        2. 服务端验证请求的合法性（机器人 token、用户权限等）
        3. 服务端返回该用户的配置信息，包括一次性的 typing_ticket
        4. 客户端使用返回的票据进行后续的输入状态操作

        获取的配置信息通常包含：
        - typing_ticket: 用于发送输入状态（正在输入）的临时票据
        - 其他机器人配置，如可用功能、权限范围、限制条件等
        - 用户特定的设置或上下文信息

        Args:
            user_id (str): 目标用户的 iLink 用户 ID。
                这是用户的唯一标识符，用于获取该用户相关的配置信息。
                注意：必须是有效的 iLink 用户 ID，而非微信原生用户 ID。
                这个 ID 通常从 get_updates 返回的消息中获取。

            context_token (str | None): 可选的上下文令牌，用于关联对话。
                这是一个可选的令牌，用于维持多轮对话的上下文。
                如果提供了此令牌，iLink 服务端会将其与当前对话关联，确保配置信息的一致性。
                在需要连续对话的场景中，应传递相同的上下文令牌。

        Returns:
            GetConfigResp: 包含 typing_ticket 等配置信息的响应对象。
            这是一个 Pydantic 模型，包含以下关键字段：
            - ret: 返回码（0 表示成功）
            - typing_ticket: 用于发送输入状态的临时票据
            - 其他可能的配置字段，如机器人权限、功能列表等

            响应对象示例：
            {
                "ret": 0,
                "typing_ticket": "ticket_abc123...",
                "features": ["typing", "markdown"],
                "permissions": ["send_text", "send_image"]
            }

        Raises:
            httpx.HTTPStatusError: 当 iLink 服务端返回非 2xx 状态码时抛出
            httpx.TimeoutException: 当请求超时时抛出
            httpx.RequestError: 当网络请求失败时抛出
            RuntimeError: 当在 async with 上下文外调用时抛出
            pydantic.ValidationError: 当响应数据格式不符合 GetConfigResp 模型时抛出

        注意事项:
        1. typing_ticket 通常是一次性的或有时间限制的，过期后需要重新获取
        2. 不同的用户可能有不同的配置信息（如功能权限不同）
        3. 建议缓存配置信息，但要注意票据的有效期
        4. 如果机器人权限变更，需要重新获取配置信息
        5. 上下文令牌有助于维护对话状态，特别是在多轮交互中

        最佳实践:
        1. 在与用户开始对话时获取配置信息
        2. 缓存 typing_ticket 并在需要发送输入状态时使用
        3. 定期检查配置信息是否过期（根据返回的过期时间或状态码）
        4. 如果发送输入状态失败（票据过期），重新调用 get_config 获取新票据
        5. 使用上下文令牌来维护复杂的多轮对话状态

        示例:
            async def handle_user_message(client: ILinkClient, user_id: str, message: str):
                # 1. 获取用户配置信息
                config = await client.get_config(user_id)

                # 2. 使用票据发送输入状态
                await client.send_typing(
                    user_id=user_id,
                    typing_ticket=config.typing_ticket,
                    status=TypingStatus.TYPING
                )

                # 3. 处理消息...
                await asyncio.sleep(1)

                # 4. 清除输入状态
                await client.send_typing(
                    user_id=user_id,
                    typing_ticket=config.typing_ticket,
                    status=TypingStatus.CLEAR
                )

                # 5. 发送回复
                reply_msg = WeixinMessage(
                    msg_type="text",
                    to_user=user_id,
                    content={"text": "处理完成"}
                )
                await client.send_message(reply_msg)
        """
        # 调用 _post 方法发送 HTTP 请求
        # 第一个参数是 API 端点路径 "ilink/bot/getconfig"
        # 第二个参数是请求体，包含目标用户 ID 和可选的上下文令牌
        data: dict[str, Any] = await self._post(
            "ilink/bot/getconfig",  # iLink 获取配置信息接口路径
            # 请求体结构，包含必需字段 ilink_user_id 和可选字段 context_token
            {
                "ilink_user_id": user_id,  # 目标用户的 iLink 用户 ID
                "context_token": context_token,  # 可选的上下文令牌
            },
        )

        # 将响应数据解析为 GetConfigResp 对象
        # 使用 Pydantic 的 model_validate 进行数据验证和类型转换
        # 这确保了响应数据的结构符合预期，提供了类型安全
        return GetConfigResp.model_validate(data)

    # -- 辅助方法（移植自 index.ts） --

    @staticmethod
    def extract_text(msg: WeixinMessage) -> str:
        """从收到的消息中提取纯文本内容。

        核心功能：从复杂的微信消息对象中提取可处理的纯文本内容。
        微信消息可能包含多种类型的内容项（文本、语音、图片、文件等），
        这个方法按照预定的优先级从消息中提取文本信息，便于后续的文本处理逻辑。

        应用场景：
        1. 机器人需要处理用户输入的文字信息
        2. 语音消息的ASR（语音识别）转写文本处理
        3. 消息预处理，为自然语言理解（NLU）提供输入
        4. 日志记录和消息分析

        提取优先级：
        1. TEXT 类型消息项 → 直接取文本（如有引用消息，前缀 "[引用: ...]"）
        2. VOICE 类型消息项 → 取语音识别(ASR)转写文本
        3. 都没有 → 返回空字符串

        设计原则：
        1. 安全性：对None值有充分的检查，避免运行时异常
        2. 可预测性：明确的优先级顺序，确保结果一致
        3. 简洁性：返回纯文本字符串，便于后续处理
        4. 完整性：对引用消息等特殊情况进行特殊处理

        Args:
            msg (WeixinMessage): 收到的微信消息对象。
                这是一个Pydantic模型，包含消息的所有信息，特别是item_list字段。
                item_list是一个列表，包含消息中的各个内容项，每个项有type和相应的数据。

        Returns:
            str: 提取到的文本内容，无文本时返回空字符串。
                返回的文本可能是：
                - 文本消息的文本内容
                - 语音消息的ASR转写文本
                - 带有引用标记的文本
                - 空字符串（当消息不包含可提取的文本时）

        """
        # 消息体为空，直接返回空字符串
        # 这是边界情况处理，避免后续对空列表的操作
        if not msg.item_list:
            return ""

        # 遍历消息中的所有内容项，按优先级匹配
        # item_list是消息内容项的列表，可能包含文本、语音、图片等多种类型
        for item in msg.item_list:
            # 优先级 1：文本消息项
            # 检查条件：
            # 1. 内容项类型是TEXT
            # 2. text_item属性存在（不为None）
            # 3. text_item.text属性存在且不为None/空
            if (
                    item.type == MessageItemType.TEXT
                    and item.text_item
                    and item.text_item.text
            ):
                # 获取引用消息信息
                ref = item.ref_msg

                # 如果消息包含引用（回复），在文本前添加引用标记
                # 引用标记格式："[引用: {引用标题}]\n"
                # 这有助于保持对话上下文
                if ref and ref.title:
                    return f"[引用: {ref.title}]\n{item.text_item.text}"

                # 无引用，直接返回文本内容
                return item.text_item.text

            # 优先级 2：语音消息的 ASR 转写文本
            # 检查条件：
            # 1. 内容项类型是VOICE
            # 2. voice_item属性存在
            # 3. voice_item.text属性存在且不为None/空
            # 注意：voice_item.text是语音识别（ASR）的转写结果
            if (
                    item.type == MessageItemType.VOICE
                    and item.voice_item
                    and item.voice_item.text
            ):
                # 返回语音转写的文本
                return item.voice_item.text

        # 所有内容项都不包含可提取的文本
        # 返回空字符串表示没有提取到文本
        return ""

    async def send_text_reply(
            self,
            to_user_id: str,
            context_token: str,
            text: str,
    ) -> None:
        """发送文本回复，自动对超长消息进行分片。

        核心功能：发送文本回复给指定用户，自动处理微信消息长度限制，支持长文本自动分片。
        这是机器人回复用户的主要方法，特别适用于需要发送长篇内容的场景。

        工作原理：
        1. 检查输入文本长度是否超过微信消息长度限制
        2. 如果超过限制，将文本按安全阈值分割为多个片段
        3. 为每个片段创建独立的微信消息对象
        4. 按顺序发送所有消息片段，确保用户按正确顺序接收

        分片策略：
        1. 短消息（≤4000字符）：直接发送
        2. 长消息（>4000字符）：按4000字符为单位切割
        3. 切割时保持文本完整性，避免在单词或句子中间切割
        4. 每个片段都作为独立消息发送，用户会收到多条消息

        Args:
            to_user_id (str): 目标用户 ID。
                接收消息的用户标识，通常是微信用户ID或企业微信用户ID。

            context_token (str): 对话上下文令牌。
                用于关联多条消息，保持对话的连贯性。同一个对话中的多条消息
                应使用相同的context_token，以便微信客户端正确显示消息线程。

            text (str): 回复文本内容。
                要发送给用户的文本内容。可以包含任何Unicode字符，包括中文、
                英文、表情符号等。如果文本超过4000字符，会自动分片发送。

        Returns:
            None: 该方法不返回任何值，所有消息发送成功时静默完成，失败时抛出异常。

        Raises:
            httpx.HTTPStatusError: 当任意一条消息发送失败时抛出
            httpx.TimeoutException: 当任意一条消息发送超时时抛出
            RuntimeError: 当在 async with 上下文外调用时抛出
            ValueError: 当参数无效时（如空文本、无效用户ID等）
        """
        # 分片策略：短消息直接发送，长消息按 MAX_MSG_LEN 字符切割
        # 检查文本长度，决定是否需要分片
        if len(text) <= MAX_MSG_LEN:
            # 文本长度在限制内，直接作为单个片段
            chunks: list[str] = [text]
        else:
            # 文本超过限制，使用正则表达式进行分割
            # 正则模式 f".{{1,{MAX_MSG_LEN}}}" 匹配 1到 MAX_MSG_LEN个任意字符
            # re.DOTALL 标志确保点号(.)匹配包括换行符在内的所有字符
            # 这样能保持文本的段落结构，不会在换行处错误分割
            chunks = re.findall(f".{{1,{MAX_MSG_LEN}}}", text, re.DOTALL)

        # 逐片构造 WeixinMessage 并发送
        # 遍历所有文本片段，为每个片段创建独立的消息对象
        for chunk in chunks:
            # 创建微信消息对象
            msg = WeixinMessage(
                to_user_id=to_user_id,  # 接收者用户ID
                from_user_id="",  # 发送者用户ID，由服务端自动填充机器人ID
                client_id=generate_client_id(),  # 生成唯一客户端消息ID，避免微信客户端的消息去重
                message_type=MessageType.BOT,  # 消息类型为机器人消息
                message_state=MessageState.FINISH,  # 消息状态为已完成（非流式传输）
                context_token=context_token,  # 上下文令牌，保持对话连贯性
                # 消息内容项列表，只包含一个文本项
                item_list=[
                    MessageItem(
                        type=MessageItemType.TEXT,  # 消息项类型为文本
                        text_item=TextItem(text=chunk),  # 文本内容
                    )
                ],
            )
            # 发送消息
            await self.send_message(msg)
            # 注意：这里没有错误处理，如果发送失败会向上抛出异常
            # 上层调用者可以根据需要捕获异常并处理

    async def show_typing(
            self,
            user_id: str,
            context_token: str | None = None,
    ) -> None:
        """向用户显示"正在输入"状态指示器。

        核心功能：向指定用户显示"对方正在输入..."的视觉提示，提升聊天交互的实时感和用户体验。
        这是一个便捷方法，封装了获取票据和发送状态两个步骤，简化了调用流程。

        工作流程：
        1. 调用 get_config 接口，获取包含 typing_ticket 的配置信息
        2. 从响应中提取 typing_ticket（票据可能有时效性）
        3. 调用 send_typing 接口，发送 TYPING 状态指示
        4. 如果任何步骤失败，静默忽略异常，不向上抛出

        注意：这个方法与 send_typing 方法的区别：
        - send_typing: 需要调用者提供 typing_ticket，适合需要重复发送状态的场景
        - show_typing: 内部获取票据并发送，适合单次触发场景

        Args:
            user_id (str): 目标用户的 iLink 用户 ID。
                接收"正在输入"状态提示的用户标识，必须是有效的 iLink 用户 ID。

            context_token (str | None): 可选的上下文令牌。
                用于关联对话上下文，传递给 get_config 接口。如果提供，iLink 服务端
                会返回与该上下文相关的配置信息。
        """
        try:
            # 步骤 1：获取 typing_ticket（每次调用都需重新获取，ticket 有时效性）
            # 调用 get_config 接口，获取用户的配置信息，包括 typing_ticket
            # 每次都重新获取是为了确保票据在有效期内，避免使用过期的票据
            config: GetConfigResp = await self.get_config(
                user_id, context_token
            )

            # 步骤 2：如果成功获取到 ticket，发送 TYPING 状态
            # 检查 config.typing_ticket 是否存在且非空
            # 如果票据存在，调用 send_typing 发送"正在输入"状态
            if config.typing_ticket:
                await self.send_typing(
                    user_id,  # 目标用户ID
                    config.typing_ticket,  # 从配置中获取的票据
                    TypingStatus.TYPING,  # 状态为"正在输入"
                )
            # 注意：如果 config.typing_ticket 为空，静默跳过，不发送状态
            # 这可能是由于服务端未返回票据，或用户权限不足

        except Exception:
            # 容错设计：typing 是锦上添花功能，失败不应影响消息收发主流程
            # 捕获所有异常并静默忽略，不记录日志，不向上抛出
            # 这样可以确保即使"正在输入"功能失效，核心消息功能仍然正常
            pass
            # 注意：在生产环境中，可能需要根据需求决定是否记录日志
            # 例如，可以添加调试级别的日志记录，但不影响程序执行

    # -- 长轮询消息循环（移植自 index.ts main()） --

    async def poll_loop(
            self,
            on_message: OnMessageCallback,
            *,
            sync_buf_store: SyncBufStore | None = None,
            context_token_store: ContextTokenStore | None = None,
            max_iterations: int | None = None,
            max_consecutive_failures: int = 3,
            short_backoff_s: float = 2.0,
            long_backoff_s: float = 60.0,
            max_short_retries: int = 30,
    ) -> None:
        """运行长轮询消息循环。

        持续从微信服务器拉取新消息并分发给业务回调。

        业务错误（ret != 0，但非 session 过期）采用双层退避策略无限重试：
        1. **短退避阶段**：每次失败等待 ``short_backoff_s`` 秒，最多连续
           ``max_short_retries`` 次。
        2. **长退避阶段**：短退避次数耗尽后，切换为每次等待
           ``long_backoff_s`` 秒，无限重试。
        3. **重置机制**：一旦收到成功响应（ret=0），短退避计数器归零，
           回到短退避阶段。

        网络异常（httpx 错误等）仍保持原有行为：连续失败达到
        ``max_consecutive_failures`` 阈值后抛出原始异常。

        Args:
            on_message: 收到用户消息时的异步回调。
                回调中的异常会被捕获并记录，但不会中断消息循环。
            sync_buf_store: 同步游标持久化存储。
                不传时使用模块级默认单例 ``default_sync_buf_store``。
            context_token_store: 上下文令牌缓存。
                不传时使用模块级默认单例 ``default_token_store``。
            max_iterations: 最大循环次数，None 表示无限循环（用于测试）。
            max_consecutive_failures: 连续网络异常失败阈值，达到后抛出异常，默认 3。
            short_backoff_s: 短退避等待时间（秒），默认 2.0。
            long_backoff_s: 长退避等待时间（秒），默认 60.0。
            max_short_retries: 短退避最大连续重试次数，达到后切换为长退避，默认 30。

        Raises:
            SessionExpiredError: 会话过期（errcode=-14），立即抛出。
            Exception: 连续网络异常达到阈值，抛出原始异常。
        """
        # 默认使用模块级单例
        if sync_buf_store is None:
            sync_buf_store = default_sync_buf_store
        if context_token_store is None:
            context_token_store = default_token_store

        # 从持久化存储恢复同步游标，实现断点续传
        sync_buf_store.load()
        sync_buf: str = sync_buf_store.get()

        # 业务错误的短退避计数器（与网络异常计数器分开）
        short_failures: int = 0
        # 网络异常的连续失败计数器
        consecutive_net_failures: int = 0
        iterations: int = 0

        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            try:
                # 长轮询拉取更新
                resp: GetUpdatesResp = await self.get_updates(sync_buf)

                # 检查业务层错误码
                has_error: bool = (
                    (resp.ret is not None and resp.ret != 0)
                    or (resp.errcode is not None and resp.errcode != 0)
                )
                if has_error:
                    # 会话过期：立即抛出异常
                    is_expired: bool = (
                        resp.errcode == SESSION_EXPIRED_ERRCODE
                        or resp.ret == SESSION_EXPIRED_ERRCODE
                    )
                    if is_expired:
                        raise SessionExpiredError(
                            "iLink 会话过期 (errcode=-14)"
                        )

                    # 一般业务错误：双层退避，永不抛异常
                    short_failures += 1
                    if short_failures <= max_short_retries:
                        # 短退避阶段
                        logger.warning(
                            "getUpdates 业务错误: ret=%s errcode=%s "
                            "(短退避 %d/%d, %.1fs)",
                            resp.ret,
                            resp.errcode,
                            short_failures,
                            max_short_retries,
                            short_backoff_s,
                        )
                        await asyncio.sleep(short_backoff_s)
                    else:
                        # 长退避阶段
                        logger.warning(
                            "getUpdates 业务错误: ret=%s errcode=%s "
                            "(短退避耗尽, 长退避 %.1fs)",
                            resp.ret,
                            resp.errcode,
                            long_backoff_s,
                        )
                        await asyncio.sleep(long_backoff_s)
                    continue

                # 成功响应，重置业务错误短退避计数 + 网络异常计数
                short_failures = 0
                consecutive_net_failures = 0

                # 持久化同步游标
                if resp.get_updates_buf:
                    sync_buf = resp.get_updates_buf
                    sync_buf_store.set(sync_buf)

                # 遍历并处理新消息
                for msg in resp.msgs or []:
                    # 缓存用户的 context_token
                    if msg.context_token and msg.from_user_id:
                        context_token_store.set(
                            msg.from_user_id, msg.context_token
                        )

                    # 只分发用户消息，忽略机器人自身消息
                    if msg.message_type != MessageType.USER:
                        continue

                    # 用户的消息处理逻辑不影响当前的循环
                    try:
                        await on_message(msg)
                    except Exception:
                        logger.exception(
                            "on_message handler error for %s",
                            msg.from_user_id,
                        )

            except SessionExpiredError:
                # 会话过期异常直接向上传播，不做退避
                raise
            except Exception:
                # 网络异常等：累加失败计数，达到阈值直接抛出原始异常
                consecutive_net_failures += 1
                logger.exception(
                    "Poll 网络异常 (%d/%d)",
                    consecutive_net_failures,
                    max_consecutive_failures,
                )
                if consecutive_net_failures >= max_consecutive_failures:
                    raise
                await asyncio.sleep(short_backoff_s)



    async def run(
            self,
            on_message: OnMessageCallback,
            *,
            sync_buf_store: SyncBufStore | None = None,
            context_token_store: ContextTokenStore | None = None,
            short_backoff_s: float = 2.0,
            long_backoff_s: float = 60.0,
            max_short_retries: int = 30,
    ) -> None:
        """启动客户端并进入长轮询消息循环。

        便捷方法，自动管理异步上下文（创建/关闭 HTTP 客户端），
        并委托 ``poll_loop`` 执行消息循环。

        Args:
            on_message: 收到用户消息时的异步回调。
            sync_buf_store: 同步游标持久化存储，不传时使用默认单例。
            context_token_store: 上下文令牌缓存，不传时使用默认单例。
            short_backoff_s: 短退避等待时间（秒），默认 2.0。
            long_backoff_s: 长退避等待时间（秒），默认 60.0。
            max_short_retries: 短退避最大连续重试次数，默认 30。

        Raises:
            SessionExpiredError: 会话过期。
            Exception: 连续网络异常达到阈值。
        """
        # 使用异步上下文管理器进入客户端上下文
        # 这会自动调用__aenter__方法，初始化HTTP会话等资源
        async with self:
            # 调用长轮询循环，开始持续监听消息
            # 该方法会不断向服务器发起请求，获取新消息
            # 收到消息后会调用on_message回调进行处理
            await self.poll_loop(
                on_message,
                sync_buf_store=sync_buf_store,
                context_token_store=context_token_store,
                short_backoff_s=short_backoff_s,
                long_backoff_s=long_backoff_s,
                max_short_retries=max_short_retries,
            )

        # 退出async with块时自动调用__aexit__
        # 确保HTTP客户端等资源被正确清理
