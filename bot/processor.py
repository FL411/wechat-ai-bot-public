"""回复处理模块"""

import re
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class ReplyProcessor:
    """回复处理类"""

    def __init__(self, config: dict):
        self.config = config
        llm_params = config.get("llm", {}).get("params", {}) or {}
        self.reply_repeat_penalty = llm_params.get("repeat_penalty", 1.08)
        self.reply_repeat_last_n = llm_params.get("repeat_last_n", 512)

    def _clean_reply_text(self, text: str) -> str:
        """清洗回复文本

        Args:
            text: 原始回复文本

        Returns:
            str: 清洗后的文本
        """
        if not text:
            return ""

        text = text.strip()

        text = re.sub(r"<\/?think>[\s\S]*?<\/?think>", "", text)

        text = re.sub(r"^```[\s\S]*?```$", "", text, flags=re.MULTILINE)
        text = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", text)

        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

        text = re.sub(r"\*{3,}", "*", text)
        text = re.sub(r"_{3,}", "_", text)

        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned_lines.append(line)

        text = "\n".join(cleaned_lines)

        if len(text) > 500:
            sentences = re.split(r"([。！？\n])", text)
            result = []
            for i in range(0, len(sentences) - 1, 2):
                result.append(sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else ""))
            if len(result) > 5:
                text = "".join(result[:5])
            elif len(result) > 3:
                text = "".join(result[:4])

        return text.strip()

    def _is_low_quality_reply(self, text: str) -> bool:
        """判断回复质量是否低

        Args:
            text: 回复文本

        Returns:
            bool: 是否低质量
        """
        if not text or len(text) < 5:
            return True

        question_count = text.count("?") + text.count("？")
        question_ratio = question_count / max(len(text), 1)
        if question_ratio > 0.15:
            return True

        repeated_patterns = [
            r"(.{3,})\1{2,}",
            r"(..+?)\1{2,}",
        ]
        for pattern in repeated_patterns:
            if re.search(pattern, text):
                return True

        low_info_patterns = [
            r"^(好的|OK|ok|嗯|啊|哦|呀|哈|嘿|喂|hi|Hi|HI|hello|Hello)\s*$",
            r"^(我不知道|I don\'t know|不清楚)\s*$",
        ]
        for pattern in low_info_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True

        return False

    def _analyze_low_quality_reason(self, text: str) -> str:
        """分析低质量原因

        Args:
            text: 回复文本

        Returns:
            str: 低质量原因
        """
        if not text:
            return "回复为空"

        if len(text) < 5:
            return "回复太短"

        question_count = text.count("?") + text.count("？")
        question_ratio = question_count / max(len(text), 1)
        if question_ratio > 0.15:
            return "反问太多"

        repeated_patterns = [
            r"(.{3,})\1{2,}",
            r"(..+?)\1{2,}",
        ]
        for pattern in repeated_patterns:
            if re.search(pattern, text):
                return "内容重复"

        return "内容质量低"

    def _regenerate_with_correction(
        self, messages: List[Dict], correction_hint: str, **kwargs
    ) -> str:
        """带纠正的重新生成

        Args:
            messages: 消息列表
            correction_hint: 纠正提示
            **kwargs: 其他参数

        Returns:
            str: 重新生成的回复
        """
        if not messages:
            return ""

        system_msg = messages[0] if messages[0].get("role") == "system" else None
        history_msgs = messages[1:] if system_msg else messages

        new_history = []
        if system_msg:
            new_history.append(system_msg)

        for msg in history_msgs[-4:]:
            new_history.append(msg)

        if correction_hint:
            new_history.append({"role": "user", "content": f"请注意：{correction_hint}"})

        return ""

    def _smart_fallback(self, original_reply: str, reason: str) -> str:
        """智能回退策略

        Args:
            original_reply: 原始回复
            reason: 低质量原因

        Returns:
            str: 回退后的回复
        """
        fallbacks = {
            "回复太短": "这个话题挺有意思的，不过我了解的也不多。",
            "反问太多": "嗯，说得对。我也这么想。",
            "内容重复": "好的，我知道了。",
            "内容质量低": "这个我也不太清楚呢，改天再说吧。",
        }

        return fallbacks.get(reason, original_reply)

    def _parse_decision_response(self, response: str) -> Optional[Dict]:
        """解析决策响应

        Args:
            response: LLM 返回的决策响应

        Returns:
            Optional[Dict]: 解析后的决策结果
        """
        if not response:
            return None

        response = response.strip()

        response = re.sub(r"<\/?think>[\s\S]*?<\/?think>", "", response)

        json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        match = re.search(json_pattern, response)

        if match:
            try:
                import json

                return json.loads(match.group(0))
            except Exception:
                pass

        return None
