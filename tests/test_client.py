"""Unit tests for ilink.client — ILinkClient."""

import json

import httpx
import pytest
import respx

from ilink.client import ILinkClient
from ilink.types import (
    ApiOptions,
    MessageItem,
    MessageItemType,
    MessageState,
    MessageType,
    TextItem,
    TypingStatus,
    WeixinMessage,
)

# 所有测试共用的 ApiOptions fixture
API = ApiOptions(base_url="https://test.example.com", token="test-token-123")


class TestPost:
    """Tests for ILinkClient._post internal method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_injects_channel_version(self) -> None:
        """_post 应在 payload 中自动注入 base_info.channel_version。"""
        route = respx.post("https://test.example.com/ilink/bot/test").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        client = ILinkClient(API)
        async with client:
            result = await client._post("ilink/bot/test", {"foo": "bar"})
        assert result == {"ok": True}
        # 验证请求体包含 base_info.channel_version
        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["base_info"]["channel_version"] == "weixin-claude-bot/0.1.0"
        assert body["foo"] == "bar"

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_raises_on_http_error(self) -> None:
        """_post 应在 HTTP 非 2xx 响应时抛出异常。"""
        respx.post("https://test.example.com/ilink/bot/fail").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        client = ILinkClient(API)
        async with client:
            with pytest.raises(httpx.HTTPStatusError):
                await client._post("ilink/bot/fail", {})

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_sets_auth_headers(self) -> None:
        """_post 应设置 Authorization 和 AuthorizationType 头。"""
        route = respx.post("https://test.example.com/ilink/bot/hdr").mock(
            return_value=httpx.Response(200, json={})
        )
        client = ILinkClient(API)
        async with client:
            await client._post("ilink/bot/hdr", {})
        request = route.calls[0].request
        assert request.headers["Authorization"] == "Bearer test-token-123"
        assert request.headers["AuthorizationType"] == "ilink_bot_token"


class TestGetUpdates:
    """Tests for ILinkClient.get_updates."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_updates_returns_messages(self) -> None:
        """正常情况下应返回 GetUpdatesResp。"""
        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            return_value=httpx.Response(200, json={
                "ret": 0,
                "msgs": [{"from_user_id": "u1", "message_type": 1}],
                "get_updates_buf": "cursor-abc",
            })
        )
        client = ILinkClient(API)
        async with client:
            resp = await client.get_updates()
        assert resp.ret == 0
        assert len(resp.msgs) == 1
        assert resp.get_updates_buf == "cursor-abc"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_updates_timeout_returns_empty(self) -> None:
        """超时时应返回空消息列表，不抛异常。"""
        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            side_effect=httpx.ReadTimeout("timeout")
        )
        client = ILinkClient(API)
        async with client:
            resp = await client.get_updates(sync_buf="old-cursor")
        assert resp.ret == 0
        assert resp.msgs == []
        assert resp.get_updates_buf == "old-cursor"


class TestSendMessage:
    """Tests for ILinkClient.send_message."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_message_posts_correctly(self) -> None:
        """send_message 应发送正确的 POST 请求。"""
        route = respx.post("https://test.example.com/ilink/bot/sendmessage").mock(
            return_value=httpx.Response(200, json={"ret": 0})
        )
        client = ILinkClient(API)
        async with client:
            msg = WeixinMessage(to_user_id="u1", message_type=MessageType.BOT)
            await client.send_message(msg)
        assert route.called


class TestSendTyping:
    """Tests for ILinkClient.send_typing."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_typing_posts_correctly(self) -> None:
        """send_typing 应发送正确的 POST 请求。"""
        route = respx.post("https://test.example.com/ilink/bot/sendtyping").mock(
            return_value=httpx.Response(200, json={"ret": 0})
        )
        client = ILinkClient(API)
        async with client:
            await client.send_typing("user-1", "ticket-abc", TypingStatus.TYPING)
        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["ilink_user_id"] == "user-1"
        assert body["typing_ticket"] == "ticket-abc"


class TestGetConfig:
    """Tests for ILinkClient.get_config."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_config_returns_typing_ticket(self) -> None:
        """get_config 应返回 typing_ticket。"""
        respx.post("https://test.example.com/ilink/bot/getconfig").mock(
            return_value=httpx.Response(200, json={
                "ret": 0,
                "typing_ticket": "tk-xyz",
            })
        )
        client = ILinkClient(API)
        async with client:
            resp = await client.get_config("user-1")
        assert resp.typing_ticket == "tk-xyz"


class TestExtractText:
    """Tests for ILinkClient.extract_text (static method)."""

    def test_extract_text_from_text_item(self) -> None:
        """应从 TEXT 类型的 item 中提取文本。"""
        msg = WeixinMessage(
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="你好"),
                )
            ]
        )
        assert ILinkClient.extract_text(msg) == "你好"

    def test_extract_text_from_voice_asr(self) -> None:
        """应从 VOICE 类型的 item 中提取 ASR 转文本。"""
        from ilink.types import VoiceItem

        msg = WeixinMessage(
            item_list=[
                MessageItem(
                    type=MessageItemType.VOICE,
                    voice_item=VoiceItem(text="语音识别文本"),
                )
            ]
        )
        assert ILinkClient.extract_text(msg) == "语音识别文本"

    def test_extract_text_with_ref_msg(self) -> None:
        """引用消息应添加 [引用: ...] 前缀。"""
        from ilink.types import RefMsg

        msg = WeixinMessage(
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="回复内容"),
                    ref_msg=RefMsg(title="原始消息"),
                )
            ]
        )
        assert ILinkClient.extract_text(msg) == "[引用: 原始消息]\n回复内容"

    def test_extract_text_empty_item_list(self) -> None:
        """空 item_list 应返回空字符串。"""
        msg = WeixinMessage(item_list=[])
        assert ILinkClient.extract_text(msg) == ""

    def test_extract_text_none_item_list(self) -> None:
        """None item_list 应返回空字符串。"""
        msg = WeixinMessage()
        assert ILinkClient.extract_text(msg) == ""


class TestSendTextReply:
    """Tests for ILinkClient.send_text_reply."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_short_text(self) -> None:
        """短文本应发送单条消息。"""
        route = respx.post("https://test.example.com/ilink/bot/sendmessage").mock(
            return_value=httpx.Response(200, json={"ret": 0})
        )
        client = ILinkClient(API)
        async with client:
            await client.send_text_reply("user-1", "ctx-token", "Hello!")
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_long_text_splits(self) -> None:
        """超过 MAX_MSG_LEN 的文本应被分段发送。"""
        route = respx.post("https://test.example.com/ilink/bot/sendmessage").mock(
            return_value=httpx.Response(200, json={"ret": 0})
        )
        client = ILinkClient(API)
        long_text = "A" * 8500  # 应分为 3 段: 4000 + 4000 + 500
        async with client:
            await client.send_text_reply("user-1", "ctx-token", long_text)
        assert route.call_count == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_text_reply_message_structure(self) -> None:
        """发送的消息应包含正确的结构。"""
        route = respx.post("https://test.example.com/ilink/bot/sendmessage").mock(
            return_value=httpx.Response(200, json={"ret": 0})
        )
        client = ILinkClient(API)
        async with client:
            await client.send_text_reply("user-1", "ctx-token", "test")
        body = json.loads(route.calls[0].request.content)
        msg = body["msg"]
        assert msg["to_user_id"] == "user-1"
        assert msg["from_user_id"] == ""
        assert msg["message_type"] == MessageType.BOT
        assert msg["message_state"] == MessageState.FINISH
        assert msg["context_token"] == "ctx-token"
        assert msg["client_id"].startswith("wcb-")
        assert msg["item_list"][0]["type"] == MessageItemType.TEXT
        assert msg["item_list"][0]["text_item"]["text"] == "test"


class TestShowTyping:
    """Tests for ILinkClient.show_typing."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_show_typing_success(self) -> None:
        """应先获取 config 再发送 typing。"""
        respx.post("https://test.example.com/ilink/bot/getconfig").mock(
            return_value=httpx.Response(200, json={
                "ret": 0,
                "typing_ticket": "ticket-1",
            })
        )
        typing_route = respx.post(
            "https://test.example.com/ilink/bot/sendtyping"
        ).mock(return_value=httpx.Response(200, json={"ret": 0}))
        client = ILinkClient(API)
        async with client:
            await client.show_typing("user-1")
        assert typing_route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_show_typing_no_ticket_skips(self) -> None:
        """没有 typing_ticket 时不应调用 sendtyping。"""
        respx.post("https://test.example.com/ilink/bot/getconfig").mock(
            return_value=httpx.Response(200, json={"ret": 0})
        )
        typing_route = respx.post(
            "https://test.example.com/ilink/bot/sendtyping"
        ).mock(return_value=httpx.Response(200, json={"ret": 0}))
        client = ILinkClient(API)
        async with client:
            await client.show_typing("user-1")
        assert not typing_route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_show_typing_error_is_silent(self) -> None:
        """show_typing 失败应静默忽略，不抛异常。"""
        respx.post("https://test.example.com/ilink/bot/getconfig").mock(
            side_effect=httpx.ConnectError("network error")
        )
        client = ILinkClient(API)
        async with client:
            # 不应抛出异常
            await client.show_typing("user-1")


class TestPollLoop:
    """Tests for ILinkClient.poll_loop."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_dispatches_user_messages(self) -> None:
        """poll_loop 应对 USER 类型消息调用 on_message 回调。"""
        received_msgs: list[WeixinMessage] = []

        async def on_message(msg: WeixinMessage) -> None:
            received_msgs.append(msg)

        # 第一次返回一条消息，第二次返回空
        responses = iter([
            httpx.Response(200, json={
                "ret": 0,
                "msgs": [{
                    "from_user_id": "u1",
                    "message_type": 1,
                    "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
                }],
                "get_updates_buf": "cursor-1",
            }),
            httpx.Response(200, json={
                "ret": 0, "msgs": [], "get_updates_buf": "cursor-1",
            }),
        ])
        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            side_effect=lambda req: next(responses)
        )

        client = ILinkClient(API)
        async with client:
            await client.poll_loop(on_message=on_message, max_iterations=2)

        assert len(received_msgs) == 1
        assert received_msgs[0].from_user_id == "u1"
        request_bodies = [
            json.loads(call.request.content) for call in respx.calls
        ]
        assert request_bodies[0]["get_updates_buf"] == ""
        assert request_bodies[1]["get_updates_buf"] == "cursor-1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_skips_non_user_messages(self) -> None:
        """poll_loop 应跳过非 USER 类型消息。"""
        received: list[WeixinMessage] = []

        async def on_message(msg: WeixinMessage) -> None:
            received.append(msg)

        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            return_value=httpx.Response(200, json={
                "ret": 0,
                "msgs": [
                    {"from_user_id": "bot", "message_type": 2},  # BOT
                    {"from_user_id": "u1", "message_type": 1},   # USER
                ],
                "get_updates_buf": "c1",
            })
        )
        client = ILinkClient(API)
        async with client:
            await client.poll_loop(on_message=on_message, max_iterations=1)
        assert len(received) == 1
        assert received[0].from_user_id == "u1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_raises_session_expired_error(self) -> None:
        """errcode -14 应立即抛出 SessionExpiredError。"""
        from ilink.client import SessionExpiredError

        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            return_value=httpx.Response(200, json={
                "ret": -14, "errcode": -14, "msgs": [],
            })
        )

        client = ILinkClient(API)
        async with client:
            with pytest.raises(SessionExpiredError):
                await client.poll_loop(
                    on_message=lambda m: None,
                    max_iterations=1,
                )

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_business_error_uses_short_backoff(
        self,
    ) -> None:
        """业务错误（ret=-1）应进行短退避重试，不抛异常。"""
        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            return_value=httpx.Response(200, json={
                "ret": -1, "errcode": -1, "msgs": [],
            })
        )

        client = ILinkClient(API)
        async with client:
            # max_iterations=5, max_short_retries=10 → 全部在短退避阶段
            # 不应抛出任何异常，循环因 max_iterations 正常结束
            await client.poll_loop(
                on_message=lambda m: None,
                max_iterations=5,
                max_short_retries=10,
                short_backoff_s=0.0,  # 测试中不实际等待
            )

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_business_error_switches_to_long_backoff(
        self,
    ) -> None:
        """短退避次数耗尽后应切换到长退避，仍不抛异常。"""
        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            return_value=httpx.Response(200, json={
                "ret": -1, "errcode": -1, "msgs": [],
            })
        )

        client = ILinkClient(API)
        async with client:
            # max_short_retries=2, max_iterations=5 → 前2次短退避，后3次长退避
            # 不应抛异常
            await client.poll_loop(
                on_message=lambda m: None,
                max_iterations=5,
                max_short_retries=2,
                short_backoff_s=0.0,
                long_backoff_s=0.0,
            )

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_resets_short_failures_on_success(
        self,
    ) -> None:
        """成功响应后应重置短退避计数器。"""
        call_count = 0

        def make_response(request):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # 前2次返回业务错误
                return httpx.Response(200, json={
                    "ret": -1, "errcode": -1, "msgs": [],
                })
            elif call_count == 3:
                # 第3次成功 → 应重置 short_failures
                return httpx.Response(200, json={
                    "ret": 0, "msgs": [], "get_updates_buf": "c1",
                })
            else:
                # 第4+次再次返回错误
                return httpx.Response(200, json={
                    "ret": -1, "errcode": -1, "msgs": [],
                })

        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            side_effect=make_response
        )

        client = ILinkClient(API)
        async with client:
            # max_short_retries=2: 如果没重置，第3次错误就会进入长退避
            # 但因为第3次成功了，short_failures 重置为0，
            # 所以第4、5次又回到短退避阶段
            await client.poll_loop(
                on_message=lambda m: None,
                max_iterations=5,
                max_short_retries=2,
                short_backoff_s=0.0,
                long_backoff_s=0.0,
            )

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_raises_on_consecutive_network_errors(
        self,
    ) -> None:
        """连续网络异常应抛出原始异常。"""
        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        client = ILinkClient(API)
        async with client:
            with pytest.raises(httpx.ConnectError):
                await client.poll_loop(
                    on_message=lambda m: None,
                    max_iterations=10,
                    max_consecutive_failures=3,
                )

    @respx.mock
    @pytest.mark.asyncio
    async def test_poll_loop_restart_uses_empty_cursor(self) -> None:
        """新的轮询实例首次请求应重新从空游标开始。"""
        seen_cursors: list[str] = []

        def make_response(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen_cursors.append(body["get_updates_buf"])
            next_cursor = f"cursor-{len(seen_cursors)}"
            return httpx.Response(
                200,
                json={"ret": 0, "msgs": [], "get_updates_buf": next_cursor},
            )

        respx.post("https://test.example.com/ilink/bot/getupdates").mock(
            side_effect=make_response
        )

        first_client = ILinkClient(API)
        async with first_client:
            await first_client.poll_loop(
                on_message=lambda m: None,
                max_iterations=2,
            )

        second_client = ILinkClient(API)
        async with second_client:
            await second_client.poll_loop(
                on_message=lambda m: None,
                max_iterations=1,
            )

        assert seen_cursors == ["", "cursor-1", ""]
