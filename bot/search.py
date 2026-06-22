"""搜索决策模块"""

import re
import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SearchDecisionCache:
    """搜索决策缓存"""

    def __init__(self, ttl_seconds: int = 300):
        self._cache = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[bool]:
        """获取缓存的搜索决策"""
        if key not in self._cache:
            return None
        entry = self._cache[key]
        if time.time() - entry["time"] > self._ttl:
            del self._cache[key]
            return None
        return entry["result"]

    def set(self, key: str, result: bool):
        """设置搜索决策缓存"""
        self._cache[key] = {"result": result, "time": time.time()}


class WebSearcher:
    """网页搜索类"""

    def __init__(self, config: dict):
        self.config = config
        self._search_enabled = config.get("search", {}).get("enabled", True)
        self._search_cache = SearchDecisionCache(ttl_seconds=300)

    def _decide_web_search(self, user_message: str, llm_backend: str = "openai_compatible") -> bool:
        """判断是否需要联网搜索

        Args:
            user_message: 用户消息
            llm_backend: LLM 后端类型

        Returns:
            bool: 是否需要搜索
        """
        if not self._search_enabled:
            return False

        cache_key = user_message[:50]
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached

        search_keywords = [
            "今天",
            "昨天",
            "明天",
            "这周",
            "上周",
            "最新",
            "现在",
            "当前",
            "今日",
            "天气",
            "温度",
            "多少度",
            "新闻",
            "消息",
            "发生",
            "哪里",
            "地址",
            "位置",
            "怎么",
            "如何",
            "方法",
            "是什么",
            "什么是",
            "为什么",
            "原因",
            "谁",
            "哪个",
            "多少",
            "价格",
            "多少钱",
        ]

        result = any(keyword in user_message for keyword in search_keywords)

        self._search_cache.set(cache_key, result)
        return result

    def _normalize_search_query(self, text: str) -> str:
        """标准化搜索查询

        Args:
            text: 原始文本

        Returns:
            str: 标准化后的查询
        """
        text = text.strip()
        text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        return text[:100]

    def _search_web(self, query: str) -> Optional[str]:
        """执行网页搜索

        Args:
            query: 搜索查询

        Returns:
            Optional[str]: 搜索结果
        """
        try:
            normalized = self._normalize_search_query(query)
            if not normalized:
                return None

            logger.info(f"[搜索] 执行搜索: {normalized}")

            return None

        except Exception as e:
            logger.error(f"[搜索] 搜索失败: {e}")
            return None

    def _quick_fact_results(self, query: str) -> Optional[str]:
        """快速事实查询

        Args:
            query: 查询内容

        Returns:
            Optional[str]: 查询结果
        """
        try:
            now = datetime.now()
            weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

            if "今天" in query or "日期" in query or "星期" in query:
                return f"今天是 {now.year}年{now.month}月{now.day}日 {weekday_names[now.weekday()]}"

            if "时间" in query or "几点" in query:
                return f"现在是 {now.strftime('%H:%M:%S')}"

            if "天气" in query:
                return "抱歉，我无法获取实时天气信息"

            return None

        except Exception as e:
            logger.error(f"[快速查询] 查询失败: {e}")
            return None
