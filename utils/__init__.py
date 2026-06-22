"""工具模块"""

from utils.exceptions import (
    WeChatBotError,
    WindowNotFoundError,
    SendMessageError,
    WindowActivationError,
    LMStudioError,
    LMStudioConnectionError,
    LMStudioTimeoutError,
    LMStudioResponseError,
    NetworkError,
    WebSocketError,
    ConfigurationError,
    SessionError,
    MemoryError,
)
from utils.data_types import Message, Session
from utils.utils import build_msg_id, message_text_for_ai

__all__ = [
    "WeChatBotError",
    "WindowNotFoundError",
    "SendMessageError",
    "WindowActivationError",
    "LMStudioError",
    "LMStudioConnectionError",
    "LMStudioTimeoutError",
    "LMStudioResponseError",
    "NetworkError",
    "WebSocketError",
    "ConfigurationError",
    "SessionError",
    "MemoryError",
    "Message",
    "Session",
    "build_msg_id",
    "message_text_for_ai",
]
