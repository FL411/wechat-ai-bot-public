"""
状态分析器
核心作用：理解用户回复的语义，决定如何回应
不是"判断用户状态"，而是"读懂用户说的话"
"""

import json
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

RESPONSE_GUIDANCE_PROMPT = """你是一个善于理解对话的人。现在你和用户有以下对话：

{chat_history}

请根据用户最后的回复，决定AI应该：
1. 继续聊天 - 用户看起来想聊
2. 收尾结束 - 用户不想聊了

返回JSON格式：
{{
    "action": "continue | end",
    "reasoning": "为什么这样判断",
    "ai_response": "AI应该怎么回应用户（1-2句话，自然的，符合人设的）"
}}

判断标准：
- 用户主动分享/问问题 → continue
- 用户回复积极（表情、感叹、问句） → continue
- 用户回复简短敷衍（嗯、哦、好） → end
- 用户明确表示忙/不方便 → end
- 用户长时间没回复 → end
"""

NO_HISTORY_PROMPT = """用户的回复是："{user_reply}"

这是对话的开始，请判断：
1. 继续聊天 - 用户看起来想聊
2. 收尾结束 - 用户不想聊了

返回JSON格式：
{{
    "action": "continue | end",
    "reasoning": "为什么这样判断",
    "ai_response": "AI应该怎么回应（1-2句话）"
}}
"""


class StateAnalyzer:
    def __init__(self, lm_client=None):
        self.lm_client = lm_client

    def _llm_chat_json(
        self, prompt: str, max_tokens: int = 500, temperature: float = 0.3
    ) -> Optional[Dict]:
        """通用 LLM Chat + JSON 解析"""
        if not self.lm_client:
            logger.warning("[状态分析] LLM客户端未初始化")
            return None

        import re

        try:
            response = self.lm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                thinking={"type": "disabled"},
            )
            if response:
                json_match = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", response)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    logger.warning("[状态分析] JSON提取失败")
            return None
        except Exception as e:
            logger.warning(f"[状态分析] LLM调用失败：{e}")
            return None

    def format_chat_history(self, messages: List[Dict]) -> str:
        """将消息列表格式化为对话记录"""
        if not messages:
            return ""
        lines = []
        for msg in messages[-6:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"用户: {content[:100]}")
            elif role == "assistant":
                lines.append(f"AI: {content[:100]}")
        return "\n".join(lines)

    def understand_reply(self, messages: List[Dict]) -> Dict:
        """理解用户回复，决定如何回应"""
        chat_history = self.format_chat_history(messages)

        if chat_history:
            prompt = RESPONSE_GUIDANCE_PROMPT.format(chat_history=chat_history)
        else:
            return {"action": "continue", "reasoning": "无历史对话，默认继续", "ai_response": None}

        result = self._llm_chat_json(prompt)

        if result:
            logger.info(
                f"[状态分析] 理解回复: action={result.get('action')}, reasoning={result.get('reasoning')}"
            )
            return result

        return self._fallback_judgment(messages)

    def _fallback_judgment(self, messages: List[Dict]) -> Dict:
        """关键词回退判断"""
        if not messages:
            return {"action": "continue", "reasoning": "无消息", "ai_response": None}

        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "").lower()
                break

        end_keywords = ["忙", "开会", "上课", "在忙", "没空", "不方便", "等会", "算了"]
        continue_keywords = ["哈哈", "想", "爱你", "好呀", "什么", "为什么", "怎么", "在干嘛"]

        if any(kw in last_user_msg for kw in end_keywords):
            return {
                "action": "end",
                "reasoning": "关键词判断：用户表示忙",
                "ai_response": "好的~你先忙~",
            }

        if any(kw in last_user_msg for kw in continue_keywords):
            return {"action": "continue", "reasoning": "关键词判断：用户积极", "ai_response": None}

        if len(last_user_msg) <= 3:
            return {"action": "end", "reasoning": "简短回复，可能敷衍", "ai_response": "好的~"}

        return {"action": "continue", "reasoning": "无法判断，默认继续", "ai_response": None}
