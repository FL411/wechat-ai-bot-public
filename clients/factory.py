"""LLM 客户端工厂"""

import logging

logger = logging.getLogger(__name__)

LEGACY_LMSTUDIO_ERROR = (
    "lmstudio 后端已移除。请迁移到统一 llm 配置："
    "llm.base_url='http://localhost:1234/v1'、llm.model='模型名'，"
    "并将生成参数放到 llm.params。"
)


def create_client(*args):
    """
    根据统一 llm 配置创建 OpenAI-compatible 客户端。

    兼容旧的 create_client(backend, config) 调用形式，但不再支持 lmstudio 后端。

    Returns:
        LLMClient 实例
    """
    if len(args) == 1:
        backend = None
        config = args[0] or {}
    elif len(args) == 2:
        backend, config = args
        config = config or {}
    else:
        raise TypeError(
            "create_client() 需要 create_client(config) 或 create_client(backend, config)"
        )

    if backend == "lmstudio" or config.get("backend") == "lmstudio":
        raise ValueError(LEGACY_LMSTUDIO_ERROR)

    if backend and backend not in ("openai", "custom", "openai_compatible"):
        raise ValueError(f"不支持的后端类型: {backend}。当前仅支持 OpenAI-compatible llm 配置。")

    from clients.openai_compatible_client import OpenAICompatibleClient

    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "https://api.openai.com/v1")
    model = config.get("model")
    timeout = config.get("timeout", 60)
    default_params = config.get("params", {}) or {}

    if not model:
        raise ValueError("llm.model 不能为空，请填写模型名称。")

    return OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        default_params=default_params,
    )
