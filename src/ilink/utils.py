"""ID generation, header building, and other small utilities."""

import base64
import random
import secrets
import time

MAX_MSG_LEN: int = 4000
"""WeChat has a ~4 096 character limit; leave some margin."""


def random_wechat_uin() -> str:
    """Generate a random X-WECHAT-UIN header value.

    Returns:
        Base64-encoded string of a random uint32 decimal.
    """
    # 生成一个32位无符号整数的随机数，范围从0到2^32-1（即0到4294967295）
    uint32 = random.randint(0, 2**32 - 1)

    # 将整数转换为十进制字符串，然后编码为字节串，最后进行base64编码
    # 返回base64编码后的字符串（解码为UTF-8字符串）
    return base64.b64encode(str(uint32).encode()).decode()


def generate_client_id() -> str:
    """Generate a unique client message ID.

    Format: ``wcb-<timestamp_ms>-<8_hex_chars>``

    Returns:
        Unique client ID string.
    """
    # 获取当前时间戳（毫秒级），乘以1000将秒转换为毫秒
    timestamp_ms = int(time.time() * 1000)

    # 生成8个十六进制字符的随机字符串（每个十六进制字符4位，8个字符共32位）
    # secrets.token_hex(4)生成8个十六进制字符，因为每个字节产生2个十六进制字符
    hex_chars = secrets.token_hex(4)

    # 按照格式拼接客户端ID：前缀"wcb"-时间戳-8位随机十六进制字符串
    return f"wcb-{timestamp_ms}-{hex_chars}"


def build_headers(token: str, body: str) -> dict[str, str]:
    """Build HTTP headers required by iLink API requests.

    Args:
        token: Bot authentication token.
        body: JSON-encoded request body (used to compute Content-Length).

    Returns:
        Dict of HTTP headers.
    """
    # 计算请求体的字节长度（UTF-8编码）
    # 注意：这里使用UTF-8编码，因为微信API通常使用UTF-8编码
    content_length = len(body.encode("utf-8"))

    # 构建并返回HTTP请求头字典
    return {
        # 指定请求体内容类型为JSON
        "Content-Type": "application/json",

        # Bearer token认证，格式为"Bearer {token}"
        "Authorization": f"Bearer {token}",

        # 指定认证类型为iLink的bot token
        "AuthorizationType": "ilink_bot_token",

        # 设置Content-Length头，值为请求体的字节长度
        "Content-Length": str(content_length),

        # 添加随机的X-WECHAT-UIN头，用于模拟不同的微信用户
        "X-WECHAT-UIN": random_wechat_uin(),
    }