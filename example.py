"""微信 Echo Bot 示例 — 使用 iLink SDK 实现消息原样回复。

运行方式:
    uv run python example.py

首次运行需要微信扫码登录，登录凭证会自动缓存到 ~/.ilink-python/，
后续运行将自动恢复凭证，无需重复扫码。
"""

from __future__ import annotations

import asyncio
import logging

from ilink import (
    ILinkClient,
    LoginResult,
    SessionExpiredError,
    load_credentials,
    login_with_qr,
    save_credentials,
)
from ilink.types import ApiOptions, WeixinMessage

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("echo-bot")


# ---------------------------------------------------------------------------
# 登录：优先从缓存恢复，否则二维码扫码
# ---------------------------------------------------------------------------


async def ensure_login() -> ApiOptions:
    """确保机器人已登录，返回可用的 API 连接配置。

    流程:
        1. 尝试从本地磁盘 (~/.ilink-python/credentials.json) 加载缓存凭证
        2. 如果缓存命中，直接复用，跳过扫码
        3. 如果缓存未命中，执行二维码扫码登录并持久化新凭证

    Returns:
        ApiOptions: 包含 base_url 和 token 的连接配置对象
    """
    # 1. 尝试从本地缓存加载凭证
    creds = load_credentials()
    if creds is not None:
        logger.info("✅ 从本地缓存恢复凭证，跳过扫码登录")
        return ApiOptions(base_url=creds.base_url, token=creds.bot_token)

    # 2. 缓存不存在，执行二维码登录
    logger.info("🔐 本地无缓存凭证，开始二维码登录...")
    result: LoginResult = await login_with_qr()

    # 3. 持久化凭证到磁盘，下次启动可直接复用
    save_credentials(
        bot_token=result.bot_token,
        account_id=result.account_id,
        base_url=result.base_url,
        user_id=result.user_id,
    )
    logger.info("💾 登录凭证已保存到本地缓存")

    return ApiOptions(base_url=result.base_url, token=result.bot_token)


# ---------------------------------------------------------------------------
# 消息回调：收到用户消息后原样回复
# ---------------------------------------------------------------------------


async def on_message(msg: WeixinMessage) -> None:
    """收到用户消息时的回调函数 — 提取文本并原样回复。

    Args:
        msg: 来自微信用户的消息对象
    """
    # 提取消息中的纯文本内容（支持文本消息和语音转文本）
    text: str = ILinkClient.extract_text(msg)

    if not text:
        logger.info("收到非文本消息，跳过 (from=%s)", msg.from_user_id)
        return

    logger.info("收到消息: [%s] %s", msg.from_user_id, text)

    # 使用全局 client 实例发送回复
    # context_token 用于关联对话上下文，从收到的消息中获取
    await client.send_text_reply(
        to_user_id=msg.from_user_id or "",
        context_token=msg.context_token or "",
        text=text,
    )
    logger.info("已回复: [%s] %s", msg.from_user_id, text)


# ---------------------------------------------------------------------------
# 全局客户端实例（在 main 中初始化）
# ---------------------------------------------------------------------------

client: ILinkClient


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def main() -> None:
    """Echo Bot 主流程：登录 → 启动轮询 → 收到消息原样回复。"""
    global client

    # 1. 确保登录
    api_options: ApiOptions = await ensure_login()

    # 2. 构造客户端
    client = ILinkClient(api_options)

    logger.info("🤖 Echo Bot 已启动，等待用户消息...")
    logger.info("按 Ctrl+C 停止运行")

    # 3. 启动长轮询消息循环
    try:
        await client.run(on_message)
    except SessionExpiredError:
        logger.error("❌ 会话已过期，请删除缓存后重新登录")
        logger.error("   重新登陆后调用save_credentials方法保存新的凭证")
    except KeyboardInterrupt:
        logger.info("🛑 用户中断，Bot 已停止")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot 已停止")
