"""QR code login flow for iLink.

iLink 二维码登录流程实现模块

完整登录流程：
1. GET get_bot_qrcode → 获取二维码字符串 + 图片URL
2. Long-poll get_qrcode_status → 轮询状态（等待/已扫描/已确认/已过期）
3. 当状态为confirmed → 接收 bot_token + ilink_bot_id + baseurl

模块设计原则：
- 异步优先：使用 asyncio 和 httpx 实现非阻塞IO
- 错误处理：完善的超时、重试和错误反馈机制
- 用户体验：终端友好，提供清晰的扫码指导和状态反馈
"""

from __future__ import annotations

import asyncio
import sys
import time

import httpx
import qrcode

from .types import (
    DEFAULT_BASE_URL,
    LOGIN_TIMEOUT_S,
    MAX_QR_REFRESH,
    QR_POLL_TIMEOUT_S,
    LoginResult,
    QRCodeResponse,
    QRStatus,
    StatusResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_qrcode(api_base_url: str) -> QRCodeResponse:
    """获取新的机器人登录二维码

    向 iLink API 服务器发起 HTTP GET 请求，获取用于微信扫码登录的二维码。
    二维码包含唯一标识符和图片数据，用于后续状态轮询。

    Args:
        api_base_url: iLink API 服务器的基础URL地址

    Returns:
        QRCodeResponse: 包含二维码标识符和图片URL/数据的响应对象
                        - qrcode: 二维码唯一标识符，用于状态轮询
                        - qrcode_img_content: 二维码图片的URL或base64编码数据

    Raises:
        httpx.HTTPStatusError: 当服务器返回非2xx状态码时
                               - 401: 认证失败
                               - 404: API端点不存在
                               - 500: 服务器内部错误
        httpx.RequestError: 网络连接错误、DNS解析失败等
        ValueError: 服务器响应格式不符合预期
    """
    # 规范化URL，确保没有多余的斜杠
    base: str = api_base_url.rstrip("/")
    # 构建完整的API端点URL
    url: str = f"{base}/ilink/bot/get_bot_qrcode"

    # 使用httpx异步客户端发起请求
    try:
        async with httpx.AsyncClient() as client:
            # 发送GET请求，附带必要的查询参数
            # bot_type=3 表示特定的机器人类型配置
            resp: httpx.Response = await client.get(url, params={"bot_type": "3"})

            # 如果HTTP状态码不是2xx，抛出异常
            resp.raise_for_status()

            # 将JSON响应解析为Pydantic模型
            # model_validate()会自动进行数据验证和类型转换
            return QRCodeResponse.model_validate(resp.json())
    except Exception as exc:
        raise RuntimeError(f"获取二维码失败: {exc}") from exc


async def _poll_status(api_base_url: str, qrcode_id: str) -> StatusResponse:
    """轮询二维码扫描状态（长轮询）

    向服务器查询指定二维码的扫描状态，使用长轮询机制减少频繁请求。
    当二维码被扫描、用户确认或过期时，服务器会立即返回状态。
    如果超时未扫描，客户端会收到"wait"状态并继续轮询。

    Args:
        api_base_url: iLink API 服务器的基础URL地址
        qrcode_id: 二维码唯一标识符，从 _fetch_qrcode() 返回的 qrcode 字段获取

    Returns:
        StatusResponse: 状态响应对象
                       - status: 二维码当前状态 (WAIT/SCANNED/CONFIRMED/EXPIRED)
                       - bot_token: 登录成功后的令牌（仅当status=CONFIRMED）
                       - ilink_bot_id: 机器人ID
                       - baseurl: API基础URL
                       - ilink_user_id: 用户ID

    Raises:
        httpx.HTTPStatusError: 服务器返回非2xx状态码
        httpx.TimeoutException: 客户端设置的超时时间到达（正常情况，返回WAIT状态）
    """
    base: str = api_base_url.rstrip("/")
    url: str = f"{base}/ilink/bot/get_qrcode_status"

    # 创建异步HTTP客户端，设置合理的超时时间（35s）
    async with httpx.AsyncClient(timeout=QR_POLL_TIMEOUT_S) as client:
        try:
            # 发送GET请求查询二维码状态
            resp: httpx.Response = await client.get(
                url,
                params={"qrcode": qrcode_id},  # 二维码标识符
                headers={"iLink-App-ClientVersion": "1"},  # 客户端版本标识
            )
            resp.raise_for_status()  # 检查HTTP状态码

            # 解析JSON响应为StatusResponse模型
            return StatusResponse.model_validate(resp.json())

        except httpx.TimeoutException:
            # 长轮询超时是正常情况，表示在此期间用户未扫码
            # 返回WAIT状态让调用方继续轮询
            return StatusResponse(status=QRStatus.WAIT)


def _display_qr(qr_img_url: str) -> None:
    """在终端显示二维码并打印备用URL

    将二维码URL转换为ASCII艺术形式在终端显示，方便用户在命令行环境中扫码。
    如果终端不支持或显示不清，同时提供原始URL作为备用方案。

    实现原理：
    1. 使用qrcode库生成二维码矩阵
    2. 将矩阵转换为ASCII字符（黑色块用██，白色块用空格）
    3. 通过invert=True在深色终端上提供更好的可视性

    Args:
        qr_img_url: 要编码为二维码的URL字符串
                    通常是微信登录页面的URL

    Raises:
        DataOverflowError: 当URL过长超过二维码容量时
        qrcode.exceptions.DataOverflowError: 数据超出二维码编码容量
    """
    # 创建QRCode对象，设置错误纠正级别为L（7%错误恢复）
    # 错误纠正允许二维码部分损坏仍可读取
    qr: qrcode.QRCode = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)

    # 将URL添加到二维码数据中
    qr.add_data(qr_img_url)

    # 自动确定最小版本和最佳拟合
    qr.make(fit=True)

    # 在终端打印ASCII格式的二维码
    # invert=True: 在深色背景终端上反色显示，提高可读性
    qr.print_ascii(invert=True)

    # 打印备用URL，以防二维码无法显示或扫描
    print(f"\n如无法显示，请在浏览器打开: {qr_img_url}\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def login_with_qr(
    api_base_url: str = DEFAULT_BASE_URL,
) -> LoginResult:
    """交互式二维码登录 - 在终端打印二维码并等待用户扫码登录

    完整的登录流程主函数：
    1. 获取初始二维码并显示
    2. 进入轮询循环，定期检查扫码状态
    3. 处理各种状态（等待、已扫描、已确认、已过期）
    4. 返回登录凭证或抛出异常

    状态机转换：
        [初始] → 获取二维码 → WAIT（等待扫码）
        WAIT → SCANNED（已扫码，等待确认）
        SCANNED → CONFIRMED（已确认，登录成功）
        WAIT/SCANNED → EXPIRED（二维码过期，需刷新）

    Args:
        api_base_url: iLink API 服务器的基础URL地址
                      默认使用 DEFAULT_BASE_URL

    Returns:
        LoginResult: 登录成功返回的结果对象，包含：
                    - bot_token: 用于后续API调用的认证令牌
                    - account_id: 机器人账户ID
                    - base_url: API基础URL（可能与传入的不同）
                    - user_id: 用户ID（可选）

    Raises:
        RuntimeError: 在以下情况抛出：
                     1. 登录总超时（LOGIN_TIMEOUT_S秒内未完成）
                     2. 二维码多次过期（超过MAX_QR_REFRESH次）
                     3. 服务器返回CONFIRMED但缺少必要字段
        httpx.HTTPStatusError: API调用HTTP错误
        asyncio.TimeoutError: 异步操作超时
    """
    # 步骤1: 获取初始二维码
    qr: QRCodeResponse = await _fetch_qrcode(api_base_url)
    refresh_count: int = 1  # 二维码刷新计数器

    # 打印扫码提示
    print("\n请使用微信扫描以下二维码：\n")

    # 在终端显示二维码
    _display_qr(qr.qrcode_img_content)

    # 设置登录截止时间，防止无限等待（8分钟）
    deadline: float = time.monotonic() + LOGIN_TIMEOUT_S

    # 标记是否已记录"已扫码"状态，避免重复输出
    scanned_logged: bool = False

    # 步骤2: 进入状态轮询循环
    while time.monotonic() < deadline:
        # 查询当前二维码状态
        status: StatusResponse = await _poll_status(api_base_url, qr.qrcode)

        # 状态处理：WAIT - 等待扫码
        if status.status == QRStatus.WAIT:
            # 打印进度点，让用户知道程序仍在运行
            sys.stdout.write(".")
            sys.stdout.flush()  # 立即刷新输出缓冲区

        # 状态处理：SCANNED - 二维码已扫描
        elif status.status == QRStatus.SCANNED:
            if not scanned_logged:
                # 首次进入SCANNED状态，提示用户在手机上确认
                print("\n\n已扫码，请在微信上确认...")
                scanned_logged = True

        # 状态处理：EXPIRED - 二维码已过期
        elif status.status == QRStatus.EXPIRED:
            refresh_count += 1

            # 检查是否超过最大刷新次数
            if refresh_count > MAX_QR_REFRESH:
                raise RuntimeError("二维码多次过期，登录超时")

            # 刷新二维码
            print(f"\n二维码已过期，正在刷新... ({refresh_count}/{MAX_QR_REFRESH})")
            qr = await _fetch_qrcode(api_base_url)
            scanned_logged = False

            # 显示新的二维码
            _display_qr(qr.qrcode_img_content)

        # 状态处理：CONFIRMED - 登录已确认
        elif status.status == QRStatus.CONFIRMED:
            # 验证服务器返回的必要字段
            if not status.ilink_bot_id or not status.bot_token:
                raise RuntimeError("登录失败：服务器未返回必要信息")

            # 登录成功
            print("\n\n✅ 微信连接成功！")

            # 返回登录结果
            return LoginResult(
                bot_token=status.bot_token,
                account_id=status.ilink_bot_id,
                base_url=status.baseurl
                or api_base_url,  # 使用服务器返回的baseurl或默认值
                user_id=status.ilink_user_id,
            )

        # 状态处理：未知状态（防御性编程）
        else:
            # 记录警告但继续轮询
            print(f"\n警告：收到未知状态: {status.status}")

        # 每次轮询后等待1秒，避免过于频繁的请求
        await asyncio.sleep(1)

    # 循环正常结束（未在deadline前返回）表示超时
    raise RuntimeError("登录超时，请重试")


if __name__ == "__main__":
    login_with_qr()
