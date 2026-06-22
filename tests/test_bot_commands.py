import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.main import WeChatAIBot


class _FakeSessionManager:
    """记录 clear_session 调用，不写盘。"""

    def __init__(self):
        self.cleared = []

    def clear_session(self, session_name):
        self.cleared.append(session_name)


class _CommandSpy:
    """绑定真实的 _handle_command，桩掉它在该路径下访问的属性。

    通过 calls 列表记录 _send_reply / _switch_persona / _generate_and_send_reply
    是否被调用，从而断言命令分发行为。
    """

    def __init__(self):
        self.session_manager = _FakeSessionManager()
        self.calls = []
        # 将未绑定方法正确绑定到桩对象
        self.handle_command = WeChatAIBot._handle_command.__get__(self, _CommandSpy)

    def _send_reply(self, text, session_name):
        self.calls.append(("send_reply", text, session_name))

    def _switch_persona(self, persona_key, session_name):
        self.calls.append(("switch_persona", persona_key, session_name))

    def _generate_and_send_reply(self, msg, session_name):
        self.calls.append(("generate", msg, session_name))


def test_st_command_is_treated_as_unknown_without_raising():
    """回归：/st 不应调用已移除的 _switch_st_character，也不应抛异常。

    修复前会抛 AttributeError；修复后落入未知命令分支，无副作用。
    """
    spy = _CommandSpy()

    # 不应抛异常
    spy.handle_command("/st some_character", "张三", {})

    # 没有任何副作用调用
    assert spy.calls == []
    assert spy.session_manager.cleared == []


def test_st_command_without_space_is_also_unknown():
    """/st（无空格）同样走未知命令分支。"""
    spy = _CommandSpy()

    spy.handle_command("/st", "张三", {})

    assert spy.calls == []


def test_new_command_still_dispatched_after_st_removal():
    """顺带覆盖 /new 正常路径，确保删除 /st 分支没误伤命令分发。"""
    spy = _CommandSpy()

    spy.handle_command("/new", "张三", {})

    assert spy.session_manager.cleared == ["张三"]
    assert ("send_reply", "好的，开始新对话！", "张三") in spy.calls
