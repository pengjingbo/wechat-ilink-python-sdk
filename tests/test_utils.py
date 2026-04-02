"""Unit tests for ilink.utils module."""

import base64
import re

from ilink.utils import (
    MAX_MSG_LEN,
    build_headers,
    generate_client_id,
    random_wechat_uin,
)


class TestMaxMsgLen:
    """Tests for MAX_MSG_LEN constant.

    这个测试类专门针对 ilink.utils 模块中的 MAX_MSG_LEN 常量进行测试。
    主要验证这个常量的值和类型是否符合预期，确保在代码中作为消息长度限制的正确性。

    测试范围：
    1. 常量值是否为4000
    2. 常量类型是否为整数

    这个常量的作用是定义微信消息的最大长度限制（微信限制约4096字符，留出96字符的余量）
    """

    def test_value_is_4000(self) -> None:
        """测试常量 MAX_MSG_LEN 的值是否为 4000"""
        # 验证 MAX_MSG_LEN 常量等于 4000
        assert MAX_MSG_LEN == 4000

    def test_type_is_int(self) -> None:
        """测试 MAX_MSG_LEN 的类型是否为整数 (int)"""
        # 验证 MAX_MSG_LEN 是整数类型
        assert isinstance(MAX_MSG_LEN, int)


class TestRandomWechatUin:
    """Tests for random_wechat_uin().

    这个测试类针对 random_wechat_uin 函数进行测试，该函数用于生成随机的 X-WECHAT-UIN 头部值。
    X-WECHAT-UIN 是微信相关的请求头，需要是一个随机的、经过 base64 编码的 32 位无符号整数。

    测试范围：
    1. 返回值是否为字符串
    2. 返回值是否为有效的 base64 编码，且解码后为十进制数字字符串
    3. 解码后的数字是否在 32 位无符号整数范围内（0 到 2^32-1）
    4. 多次调用是否可能返回不同的值（测试随机性）

    这些测试确保函数生成的 UIN 符合微信 API 的要求格式，并且具有良好的随机性。
    """

    def test_returns_str(self) -> None:
        """测试 random_wechat_uin 返回值的类型为字符串"""
        # 调用函数获取结果
        result = random_wechat_uin()
        # 验证返回结果是字符串类型
        assert isinstance(result, str)

    def test_is_valid_base64(self) -> None:
        """测试返回的字符串是有效的 base64 编码，并且解码后是十进制数字字符串"""
        # 调用函数获取结果
        result = random_wechat_uin()
        # 尝试对结果进行 base64 解码
        decoded = base64.b64decode(result)
        # 验证解码后的字节串是十进制数字（即只包含0-9的字符）
        assert decoded.isdigit()

    def test_decoded_value_within_uint32_range(self) -> None:
        """测试 base64 解码后的十进制数字在 0 到 2^32-1 的范围内（无符号32位整数）"""
        # 进行50次随机测试，确保覆盖随机性
        for _ in range(50):
            result = random_wechat_uin()
            # 解码 base64 字符串并转换为数字
            decoded = base64.b64decode(result).decode()
            num = int(decoded)
            # 验证数字在 32 位无符号整数范围内
            assert 0 <= num <= 2**32 - 1

    def test_two_calls_can_differ(self) -> None:
        """测试多次调用 random_wechat_uin 可能返回不同的值（随机性测试）"""
        # 调用20次函数，将结果收集到集合中
        results = {random_wechat_uin() for _ in range(20)}
        # 验证集合中至少有两个不同的值（由于随机性，通常集合大小大于1）
        assert len(results) > 1


class TestGenerateClientId:
    """Tests for generate_client_id().

    这个测试类针对 generate_client_id 函数进行测试，该函数用于生成唯一的客户端消息 ID。
    客户端 ID 的格式为：wcb-<timestamp_ms>-<8_hex_chars>，其中：
    - wcb: 固定前缀
    - timestamp_ms: 当前时间戳（毫秒级）
    - 8_hex_chars: 8个十六进制字符的随机字符串

    测试范围：
    1. 返回值是否为字符串
    2. 是否以 'wcb-' 开头
    3. 是否符合预期的格式模式
    4. 生成的100个ID是否都是唯一的（测试唯一性）

    这些测试确保生成的客户端ID格式正确，并且具有足够的唯一性，避免在分布式系统中产生冲突。
    """

    def test_returns_str(self) -> None:
        """测试 generate_client_id 返回值的类型为字符串"""
        result = generate_client_id()
        # 验证返回结果是字符串类型
        assert isinstance(result, str)

    def test_prefix_is_wcb(self) -> None:
        """测试生成的客户端ID以 'wcb-' 开头"""
        result = generate_client_id()
        # 验证字符串以 "wcb-" 开头
        assert result.startswith("wcb-")

    def test_format_matches_pattern(self) -> None:
        """测试生成的客户端ID格式符合 'wcb-<timestamp_ms>-<8_hex_chars>' 模式"""
        result = generate_client_id()
        # 定义正则表达式模式：wcb-开头，然后是13位以上的时间戳，接着是连字符，最后是8个十六进制字符
        pattern = r"^wcb-\d{13,}-[0-9a-f]{8}$"
        # 验证结果匹配正则表达式
        assert re.match(pattern, result), f"'{result}' does not match pattern"

    def test_uniqueness(self) -> None:
        """测试 generate_client_id 生成的100个ID都是唯一的"""
        # 生成100个客户端ID
        ids = [generate_client_id() for _ in range(100)]
        # 将列表转换为集合，如果集合大小等于列表大小，说明所有ID都是唯一的
        assert len(set(ids)) == 100


class TestBuildHeaders:
    """Tests for build_headers().

    这个测试类针对 build_headers 函数进行测试，该函数用于构建 iLink API 请求所需的 HTTP 头部。
    函数接收 token 和请求体 body，返回包含以下字段的字典：
    - Content-Type: 固定为 application/json
    - Authorization: Bearer <token>
    - AuthorizationType: ilink_bot_token
    - Content-Length: 请求体的 UTF-8 编码字节长度
    - X-WECHAT-UIN: 随机的微信 UIN（由 random_wechat_uin 生成）

    测试范围：
    1. 返回值是否为字典
    2. Content-Type 是否正确
    3. Authorization 头的格式是否正确
    4. AuthorizationType 是否正确
    5. Content-Length 对于 ASCII 和 Unicode 请求体是否正确
    6. X-WECHAT-UIN 头是否存在且有效

    这些测试确保构建的 HTTP 头部符合 iLink API 的要求，特别是认证和内容长度的准确性。
    """

    def test_returns_dict(self) -> None:
        """测试 build_headers 返回值的类型为字典"""
        # 使用示例token和请求体调用函数
        result = build_headers("tok_123", '{"key": "value"}')
        # 验证返回结果是字典类型
        assert isinstance(result, dict)

    def test_content_type_json(self) -> None:
        """测试返回的headers中包含Content-Type字段，且值为'application/json'"""
        result = build_headers("tok_123", "{}")
        # 验证Content-Type头是正确的JSON类型
        assert result["Content-Type"] == "application/json"

    def test_authorization_bearer(self) -> None:
        """测试Authorization头的格式为'Bearer <token>'"""
        result = build_headers("my_token", "{}")
        # 验证Authorization头包含Bearer令牌
        assert result["Authorization"] == "Bearer my_token"

    def test_authorization_type(self) -> None:
        """测试AuthorizationType头的值为'ilink_bot_token'"""
        result = build_headers("tok", "{}")
        # 验证AuthorizationType头是正确的类型
        assert result["AuthorizationType"] == "ilink_bot_token"

    def test_content_length_ascii(self) -> None:
        """测试Content-Length头的值对于ASCII请求体是正确的（UTF-8编码后的字节长度）"""
        # 使用ASCII字符串作为请求体
        body = '{"hello": "world"}'
        result = build_headers("tok", body)
        # 验证Content-Length等于请求体UTF-8编码的字节长度
        assert result["Content-Length"] == str(len(body.encode("utf-8")))

    def test_content_length_unicode(self) -> None:
        """测试Content-Length头的值对于包含Unicode字符的请求体是正确的"""
        # 使用包含Unicode字符的请求体
        body = '{"text": "你好世界"}'
        result = build_headers("tok", body)
        # 验证Content-Length等于请求体UTF-8编码的字节长度
        assert result["Content-Length"] == str(len(body.encode("utf-8")))

    def test_x_wechat_uin_present(self) -> None:
        """测试返回的headers中包含X-WECHAT-UIN字段"""
        result = build_headers("tok", "{}")
        # 验证X-WECHAT-UIN头存在
        assert "X-WECHAT-UIN" in result

    def test_x_wechat_uin_is_valid_base64(self) -> None:
        """测试X-WECHAT-UIN头的值是有效的base64编码，并且解码后是十进制数字"""
        result = build_headers("tok", "{}")
        # 获取X-WECHAT-UIN头的值
        uin = result["X-WECHAT-UIN"]
        # 尝试对其进行base64解码
        decoded = base64.b64decode(uin)
        # 验证解码后的字节串是十进制数字
        assert decoded.isdigit()