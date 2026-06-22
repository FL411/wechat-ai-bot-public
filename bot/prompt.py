"""Prompt 构建模块"""

import os
import yaml
import logging
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")


class PromptBuilder:
    """Prompt 构建类"""

    def __init__(
        self, config: dict, schedule_manager=None, enhanced_memory=None, ai_state_system=None
    ):
        self.config = config
        self.schedule_manager = schedule_manager
        self.enhanced_memory = enhanced_memory
        self.ai_state_system = ai_state_system
        self._personas = {}
        self._system_prompt = ""
        self._loaded = False

    def _load_prompt(self, filename: str) -> str:
        """加载提示词文件

        Args:
            filename: 文件名

        Returns:
            str: 文件内容
        """
        filepath = os.path.join(PROMPTS_DIR, filename)
        if not os.path.exists(filepath):
            logger.warning(f"提示词文件不存在: {filepath}")
            return ""

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            logger.debug(f"已加载提示词: {filename} ({len(content)} 字符)")
            return content
        except Exception as e:
            logger.error(f"加载提示词失败: {e}")
            return ""

    def _load_system_prompt(self) -> str:
        """加载系统提示词"""
        return self._load_prompt("system.yaml")

    def _load_personas(self) -> Dict:
        """加载人设配置"""
        personas_file = os.path.join(PROMPTS_DIR, "personas.yaml")
        if not os.path.exists(personas_file):
            return {}

        try:
            with open(personas_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return config.get("personas", {})
        except Exception as e:
            logger.error(f"加载人设配置失败: {e}")
            return {}

    def ensure_loaded(self):
        """确保提示词已加载"""
        if self._loaded:
            return
        self._system_prompt = self._load_system_prompt()
        self._personas = self._load_personas()
        self._loaded = True

    def _get_persona_prompt(self, persona_key: str) -> str:
        """获取人设 prompt

        Args:
            persona_key: 人设标识

        Returns:
            str: 人设 prompt 内容
        """
        self.ensure_loaded()

        if not persona_key or persona_key == "normal":
            return ""

        persona_config = self._personas.get(persona_key, {})
        prompt_file = persona_config.get("prompt_file", f"{persona_key}.yaml")

        return self._load_prompt(prompt_file)

    def _current_time_reference(self) -> str:
        """获取当前时间参考"""
        now = datetime.now()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        time_ref = f"现在是 {now.year}年{now.month}月{now.day}日 {weekday_names[now.weekday()]} {now.strftime('%H:%M')}"

        if self.schedule_manager:
            daily = self.schedule_manager.get_current_daily_schedule()
            if daily:
                notes = daily.get("notes", "")
                meals = daily.get("meals", {})
                if notes:
                    time_ref += f"\n今日备注：{notes}"
                if meals:
                    meal_info = " | ".join([f"{k}：{v}" for k, v in meals.items() if v])
                    if meal_info:
                        time_ref += f"\n今日三餐：{meal_info}"

        if self.ai_state_system:
            state = self.ai_state_system.get_current_state()
            if state:
                time_ref += f"\n当前状态：{state}"

        return time_ref

    def _build_prompt_messages(
        self, user_message: str, session_manager, context: Dict
    ) -> List[Dict]:
        """构建 prompt 消息列表

        Args:
            user_message: 用户消息
            session_manager: 会话管理器
            context: 上下文信息

        Returns:
            List[Dict]: 消息列表
        """
        self.ensure_loaded()

        current_persona = context.get("current_persona", "normal")

        messages = []

        system_parts = []

        if self._system_prompt:
            system_parts.append(self._system_prompt)

        persona_prompt = self._get_persona_prompt(current_persona)
        if persona_prompt:
            system_parts.append(f"\n\n{persona_prompt}")

        time_ref = self._current_time_reference()
        if time_ref:
            system_parts.append(f"\n\n# 当前时间\n{time_ref}")

        if system_parts:
            messages.append({"role": "system", "content": "\n".join(system_parts)})

        if session_manager:
            history = session_manager.get_messages()
            for msg in history[-20:]:
                messages.append(msg)

        messages.append({"role": "user", "content": user_message})

        return messages

    def _trim_prompt_messages(self, messages: List[Dict], max_chars: int = 8000) -> List[Dict]:
        """裁剪 prompt 消息

        Args:
            messages: 原始消息列表
            max_chars: 最大字符数

        Returns:
            List[Dict]: 裁剪后的消息列表
        """
        if not messages:
            return messages

        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars <= max_chars:
            return messages

        if len(messages) <= 2:
            return messages

        result = [messages[0]]

        for msg in reversed(messages[1:]):
            total_chars -= len(msg.get("content", ""))
            if total_chars <= max_chars * 0.8:
                result.insert(1, msg)
            else:
                break

        return result if len(result) > 1 else messages
