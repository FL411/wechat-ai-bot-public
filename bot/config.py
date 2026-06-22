"""配置加载模块"""

import os
import yaml
import logging

logger = logging.getLogger(__name__)


def _get_config_value(cfg: dict, *keys, default=None):
    """安全获取配置值"""
    value = cfg
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return default
        if value is None:
            return default
    return value


def load_bot_config(config_file: str = None) -> dict:
    """加载 bot_config.yaml 配置

    Args:
        config_file: 配置文件路径，默认使用项目根目录下的 bot_config.yaml

    Returns:
        dict: 配置字典
    """
    if config_file is None:
        config_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_config.yaml"
        )

    if not os.path.exists(config_file):
        logger.warning(f"配置文件不存在: {config_file}")
        return {}

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logger.info(f"已加载配置: {config_file}")
        return config or {}
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return {}


class Config:
    """配置类"""

    def __init__(self, config_file: str = None):
        self._config = load_bot_config(config_file)

    def get(self, *keys, default=None):
        """获取配置值"""
        return _get_config_value(self._config, *keys, default=default)

    @property
    def llm_base_url(self) -> str:
        return self.get("llm", "base_url", default="http://localhost:1234/v1")

    @property
    def llm_model(self) -> str:
        return self.get("llm", "model", default="")

    @property
    def search_enabled(self) -> bool:
        return self.get("search", "enabled", default=True)

    @property
    def ignore_group_chat(self) -> bool:
        return self.get("wechat", "ignore_group_chat", default=True)

    @property
    def webui_url(self) -> str:
        return self.get("wechat", "webui_url", default="http://localhost:5678")

    @property
    def ws_url(self) -> str:
        return self.get("wechat", "ws_url", default="ws://localhost:5679")

    @property
    def auto_schedule(self) -> bool:
        return self.get("bot", "auto_schedule", default=True)

    @property
    def use_bge(self) -> bool:
        return self.get("bot", "use_bge", default=False)

    @property
    def use_bm25(self) -> bool:
        return self.get("bot", "use_bm25", default=True)
