from typing import List, Dict, Any, Optional
import threading

import httpx
from loguru import logger

from clients.base import LLMClient


class OpenAICompatibleClient(LLMClient):
    """
    OpenAI 兼容 API 客户端
    支持: OpenAI, Anthropic, DeepSeek, 硅基流动, 阿里云百炼, Groq 等
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-3.5-turbo",
        timeout: int = 60,
        default_params: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化客户端

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            model: 模型名称
            timeout: 请求超时时间（秒）
            default_params: 默认生成参数，会透传到 /chat/completions
        """
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.default_params = dict(default_params or {})

        self.chat_url = f"{self.base_url}/chat/completions"

        # 创建 HTTP 客户端
        self._client = httpx.Client(timeout=timeout, headers=self._build_headers())
        self._lock = threading.Lock()

        logger.info(f"[OpenAI Compatible] 初始化客户端: {base_url}, 模型: {model}")

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def close(self):
        """关闭客户端"""
        with self._lock:
            self._client.close()
            self._client = httpx.Client(timeout=self.timeout, headers=self._build_headers())

    def reset(self):
        """重置连接状态"""
        self.close()

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """标准化消息格式"""
        normalized = []
        for item in messages or []:
            role = str(item.get("role", "")).strip()
            if not role:
                continue

            content = item.get("content", "")

            # 处理多模态内容
            if isinstance(content, list):
                normalized.append({"role": role, "content": content})
                continue

            # 处理文本内容
            content = str(content).strip()
            if not content:
                continue

            normalized.append({"role": role, "content": content})

        return normalized

    def _ensure_user_query(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """确保有用户消息"""
        has_user = any(m.get("role") == "user" for m in messages)

        if not has_user:
            messages.append({"role": "user", "content": "请继续对话。"})
            return messages

        # 确保最后一条是用户消息
        if messages[-1].get("role") != "user":
            for item in reversed(messages):
                if item.get("role") == "user":
                    messages.append({"role": "user", "content": item.get("content")})
                    break

        return messages

    def chat(
        self,
        messages: Any,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表
            temperature: 温度参数
            top_p: top_p 参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Returns:
            AI 回复内容
        """
        try:
            # 标准化消息
            if isinstance(messages, str):
                messages = [{"role": "user", "content": messages}]

            messages = self._normalize_messages(messages)
            messages = self._ensure_user_query(messages)

            # 构建请求
            payload = {
                "model": self.model,
                "messages": messages,
            }
            payload.update({k: v for k, v in self.default_params.items() if v is not None})

            call_params = {
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                **kwargs,
            }
            payload.update({k: v for k, v in call_params.items() if v is not None})

            # 发送请求
            with self._lock:
                response = self._client.post(self.chat_url, json=payload)

            response.raise_for_status()
            data = response.json()

            # 提取回复
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "message" in choice:
                    content = choice["message"].get("content", "")
                    return str(content).strip()

            logger.warning(f"[OpenAI Compatible] 无法解析响应: {data}")
            return ""

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[OpenAI Compatible] HTTP 错误: {e.response.status_code} - {e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"[OpenAI Compatible] 请求失败: {e}")
            raise
