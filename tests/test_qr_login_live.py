"""真实联网二维码登录测试脚本。"""

from __future__ import annotations

import asyncio

from ilink.auth import login_with_qr


async def main() -> None:
    """运行真实联网二维码登录测试。"""
    print("开始执行真实二维码登录测试，请使用微信扫码并确认。")

    try:
        result = await login_with_qr()
    except Exception as exc:
        print(f"二维码登录测试失败: {exc}")
        raise SystemExit(1) from exc

    print("二维码登录测试成功。")
    print(f"account_id: {result.account_id}")
    print(f"base_url: {result.base_url}")
    print(f"user_id: {result.user_id}")


if __name__ == "__main__":
    asyncio.run(main())