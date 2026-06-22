"""消息发送模块"""

import time
import logging
import pyperclip
import pyautogui

logger = logging.getLogger(__name__)


def send_hotkey(*keys):
    """发送热键"""
    for key in keys:
        pyautogui.keyDown(key)
    time.sleep(0.05)
    for key in keys:
        pyautogui.keyUp(key)
    time.sleep(0.05)


class MessageSender:
    """消息发送类"""

    def __init__(self, window_controller=None):
        self.window_controller = window_controller

    def _send_single(self, text: str, delay_per_char: float = 0.05) -> bool:
        """发送单条消息（打字机效果）

        Args:
            text: 要发送的文本
            delay_per_char: 每个字符的延迟（秒）

        Returns:
            bool: 发送是否成功
        """
        if not text:
            return True

        try:
            pyperclip.copy(text)

            send_hotkey("ctrl", "a")
            time.sleep(0.05)

            send_hotkey("ctrl", "v")
            time.sleep(0.1)

            send_hotkey("enter")
            time.sleep(0.2)

            logger.debug(f"[send] 消息发送成功: {text[:30]}...")
            return True

        except Exception as e:
            logger.error(f"[send] 发送消息失败: {e}")
            return False

    def _send_single_message(self, msg: dict, session_name: str, switch_chat: bool = True) -> bool:
        """发送单条消息到指定会话

        Args:
            msg: 消息字典，包含 content 字段
            session_name: 目标会话名称
            switch_chat: 是否需要切换聊天窗口

        Returns:
            bool: 发送是否成功
        """
        content = msg.get("content", "")
        if not content:
            return True

        if switch_chat and self.window_controller:
            if not self.window_controller.switch_chat(session_name):
                return False
        elif self.window_controller:
            if not self.window_controller.focus_chat_input():
                return False

        if self.window_controller and not self.window_controller.focus_chat_input():
            return False

        return self._send_single(content)

    def _split_message(self, text: str, min_length: int = 50, max_parts: int = 5) -> list:
        """拆分长消息为多个部分

        Args:
            text: 原始文本
            min_length: 每部分最小长度
            max_parts: 最大分段数

        Returns:
            list: 拆分后的文本列表
        """
        if len(text) <= min_length:
            return [text]

        import re

        split_pattern = r"([。！？\n]+)"
        parts = re.split(split_pattern, text)

        sentences = []
        for i in range(0, len(parts) - 1, 2):
            sentence = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
            if sentence.strip():
                sentences.append(sentence)

        if not sentences:
            sentences = [text]

        result = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) <= min_length * 1.5 or not current:
                current += sentence
            else:
                if current.strip():
                    result.append(current.strip())
                current = sentence

        if current.strip():
            result.append(current.strip())

        if len(result) > max_parts:
            chunk_size = len(text) // max_parts
            result = []
            for i in range(max_parts):
                start = i * chunk_size
                end = start + chunk_size if i < max_parts - 1 else len(text)
                chunk = text[start:end].strip()
                if chunk:
                    result.append(chunk)

        return result if result else [text]

    def send_message(self, content: str, chat_name: str = "") -> bool:
        """发送消息，支持分段发送

        Args:
            content: 消息内容
            chat_name: 目标会话名称

        Returns:
            bool: 发送是否成功
        """
        if not self.window_controller:
            logger.error("窗口控制器未初始化")
            return False

        parts = self._split_message(content)

        if len(parts) > 1:
            logger.info(f"[send_message] 分段发送 {len(parts)} 条消息")
            for i, part in enumerate(parts):
                logger.info(f"[send_message] 第{i+1}条: {part[:30]}...")
                if not self._send_single_message(
                    {"content": part}, chat_name, switch_chat=(i == 0)
                ):
                    return False
                if i < len(parts) - 1:
                    time.sleep(1.5)
            return True
        else:
            return self._send_single_message({"content": content}, chat_name, switch_chat=True)
