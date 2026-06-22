from typing import Dict, Optional, Any
from enum import IntEnum
from dataclasses import dataclass
from datetime import datetime


class MessageType(IntEnum):
    TEXT = 1  # 文本
    IMAGE = 3  # 图片
    VOICE = 34  # 语音
    CARD = 42  # 名片
    VIDEO = 43  # 视频
    EMOJI = 47  # 表情
    LOCATION = 48  # 位置
    LINK_FILE = 49  # 链接/文件
    CALL = 50  # 通话
    SYSTEM = 10000  # 系统
    REVOKE = 10002  # 撤回

    @property
    def label(self) -> str:
        labels = {
            1: "文本",
            3: "图片",
            34: "语音",
            42: "名片",
            43: "视频",
            47: "表情",
            48: "位置",
            49: "链接/文件",
            50: "通话",
            10000: "系统",
            10002: "撤回",
        }
        return labels.get(self, f"type={self}")

    @property
    def icon(self) -> str:
        icons = {
            1: "💬",
            3: "🖼️",
            34: "🎤",
            42: "👤",
            43: "🎬",
            47: "😀",
            48: "📍",
            49: "🔗",
            50: "📞",
            10000: "⚙️",
            10002: "↩️",
        }
        return icons.get(self, "📨")


@dataclass
class Message:
    username: str = ""
    type: int = 1
    content: str = ""
    timestamp: int = 0
    sender: str = ""
    chat: str = ""
    rich: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, d: Dict) -> "Message":
        return cls(
            username=d.get("username", ""),
            type=d.get("type", 1),
            content=d.get("content", ""),
            timestamp=d.get("timestamp", 0),
            sender=d.get("sender", ""),
            chat=d.get("chat", ""),
            rich=d.get("rich"),
        )

    @property
    def msg_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)

    @property
    def is_voice(self) -> bool:
        if self.rich:
            return str(self.rich.get("type", "")).lower() == "voice"
        return False

    @property
    def transcript(self) -> str:
        if self.rich:
            return str(self.rich.get("transcript", "")).strip()
        return ""


def build_msg_id(msg: Dict) -> str:
    """生成消息唯一 ID"""
    transcript = ""
    rich = msg.get("rich")
    if isinstance(rich, dict):
        transcript = str(rich.get("transcript", "")).strip()
    return f"{msg.get('timestamp', 0)}|{msg.get('username', '')}|{msg.get('type', '')}|{msg.get('sender', '')}|{msg.get('content', '')}|{transcript}"


def message_text_for_ai(msg: Dict) -> str:
    """提取用于 AI 处理的消息文本"""
    rich = msg.get("rich")
    if isinstance(rich, dict):
        rich_type = str(rich.get("type", "")).strip().lower()
        transcript = str(rich.get("transcript", "")).strip()
        if rich_type == "voice":
            return transcript
    msg_type = str(msg.get("type", "")).strip()
    if msg_type == "语音":
        return ""
    return str(msg.get("content", "")).strip()


def setup_logger(name: str = "wechat", level: str = "INFO", log_dir: str = "logs") -> None:
    """配置 loguru 日志（统一格式）"""
    import sys
    import os
    from loguru import logger

    logger.remove()

    console_format = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    logger.add(sys.stderr, level=level, format=console_format, colorize=True)

    if log_dir and os.path.isdir(log_dir):
        file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
        logger.add(
            os.path.join(log_dir, f"{name}_{{time:YYYYMMDD}}.log"),
            rotation="10 MB",
            retention="7 days",
            level="DEBUG",
            format=file_format,
            encoding="utf-8",
        )
