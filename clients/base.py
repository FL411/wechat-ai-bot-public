"""LLM 客户端基类"""

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """LLM 客户端抽象基类"""

    @abstractmethod
    def chat(self, messages: Any, **kwargs) -> str:
        """发送聊天请求"""
        pass

    @abstractmethod
    def reset(self) -> None:
        """重置对话上下文"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭客户端"""
        pass
