import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.wechat_adapter import WeChatMessageAdapter


def test_adapter_ignores_explicit_outgoing_direction():
    adapter = WeChatMessageAdapter(enabled=True)
    assert adapter.should_ignore({"direction": "out", "content": "hello"}) is True


def test_adapter_filters_sent_echo_in_same_session():
    adapter = WeChatMessageAdapter(enabled=True, echo_window_seconds=120)
    adapter.record_sent("张三", "你好呀~")

    assert (
        adapter.should_ignore(
            {
                "chat": "张三",
                "username": "wxid_123",
                "content": "你好呀~",
                "timestamp": 1,
            }
        )
        is True
    )


def test_adapter_does_not_filter_other_session_same_text():
    adapter = WeChatMessageAdapter(
        enabled=True, echo_window_seconds=120, cross_session_window_seconds=0
    )
    adapter.record_sent("张三", "你好呀~")

    assert (
        adapter.should_ignore(
            {
                "chat": "李四",
                "username": "wxid_456",
                "content": "你好呀~",
                "timestamp": 1,
            }
        )
        is False
    )


def test_adapter_normalizes_session_fields():
    adapter = WeChatMessageAdapter(enabled=True)
    msg = adapter.normalize({"chat": "张三", "isGroup": False})

    assert msg["session_name"] == "张三"
    assert msg["is_group"] is False


def test_adapter_filters_cross_session_echo_in_short_window():
    adapter = WeChatMessageAdapter(
        enabled=True, echo_window_seconds=120, cross_session_window_seconds=20
    )
    adapter.record_sent("张三", "刚刚这条是我发的")

    assert (
        adapter.should_ignore(
            {
                "chat": "wxid_unknown",
                "username": "wxid_unknown",
                "content": "刚刚这条是我发的",
                "timestamp": 1,
            }
        )
        is True
    )
