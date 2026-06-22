"""
AI状态系统
根据当前时间 + 日程，计算AI的状态
"""

import datetime
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AIState:
    IDLE = "idle"
    ABOUT_TO_START = "about_to_start"
    ONGOING = "ongoing"
    JUST_FINISHED = "just_finished"
    FINISHED_LONG_AGO = "finished_long_ago"
    RESTING = "resting"


class AIStateSystem:
    """
    AI状态计算器
    根据当前时间和日程，返回AI的状态
    """

    def __init__(self, schedule_manager=None):
        self.schedule_manager = schedule_manager

    def _get_effective_date(self) -> datetime.date:
        """获取有效的日期（考虑凌晨2点前算昨天）"""
        now = datetime.datetime.now()
        hour = now.hour

        if hour < 6:
            return (now - datetime.timedelta(days=1)).date()
        return now.date()

    def _parse_time(self, time_str: str) -> int:
        """解析时间字符串为分钟数"""
        try:
            if "-" in time_str:
                time_str = time_str.split("-")[0]
            if ":" in time_str:
                parts = time_str.split(":")
                return int(parts[0]) * 60 + int(parts[1])
            return int(time_str) * 60
        except Exception:
            return 0

    def _get_time_in_minutes(self) -> int:
        """获取当前时间的分钟数"""
        now = datetime.datetime.now()
        return now.hour * 60 + now.minute

    def get_current_activity(self, persona_key: str = "normal") -> Optional[Dict]:
        """获取当前正在进行的活动"""
        if not self.schedule_manager:
            return None

        try:
            schedule = self.schedule_manager.get_current_schedule(persona_key)
            if not schedule.get("daily_plan"):
                return None

            activities = schedule["daily_plan"].get("activities", [])
            current_minutes = self._get_time_in_minutes()

            for act in activities:
                time_range = act.get("time", "")
                if "-" not in time_range:
                    continue

                try:
                    start_str, end_str = time_range.split("-")
                    start_minutes = self._parse_time(start_str)
                    end_minutes = self._parse_time(end_str)

                    if start_minutes <= current_minutes <= end_minutes:
                        return act
                except Exception:
                    continue

            return None
        except Exception as e:
            logger.warning(f"[状态系统] 获取当前活动失败: {e}")
            return None

    def get_upcoming_activity(
        self, persona_key: str = "normal", within_minutes: int = 60
    ) -> Optional[Dict]:
        """获取即将开始的活动（当前时间后30分钟内）"""
        if not self.schedule_manager:
            return None

        try:
            schedule = self.schedule_manager.get_current_schedule(persona_key)
            if not schedule.get("daily_plan"):
                return None

            activities = schedule["daily_plan"].get("activities", [])
            current_minutes = self._get_time_in_minutes()

            for act in activities:
                time_range = act.get("time", "")
                if "-" not in time_range:
                    continue

                try:
                    start_str, end_str = time_range.split("-")
                    start_minutes = self._parse_time(start_str)

                    if current_minutes < start_minutes <= current_minutes + within_minutes:
                        return act
                except Exception:
                    continue

            return None
        except Exception:
            return None

    def get_last_activity(self, persona_key: str = "normal") -> Optional[Dict]:
        """获取最近结束的活动"""
        if not self.schedule_manager:
            return None

        try:
            schedule = self.schedule_manager.get_current_schedule(persona_key)
            if not schedule.get("daily_plan"):
                return None

            activities = schedule["daily_plan"].get("activities", [])
            current_minutes = self._get_time_in_minutes()

            last_act = None
            for act in activities:
                time_range = act.get("time", "")
                if "-" not in time_range:
                    continue

                try:
                    end_str = time_range.split("-")[1] if "-" in time_range else time_range
                    end_minutes = self._parse_time(end_str)

                    if end_minutes < current_minutes:
                        last_act = act
                except Exception:
                    continue

            return last_act
        except Exception:
            return None

    def get_activity_state(self, activity: Optional[Dict]) -> str:
        """判断活动的状态"""
        if not activity:
            return AIState.IDLE

        time_range = activity.get("time", "")
        if "-" not in time_range:
            return AIState.IDLE

        try:
            start_str, end_str = time_range.split("-")
            start_minutes = self._parse_time(start_str)
            end_minutes = self._parse_time(end_str)
            current_minutes = self._get_time_in_minutes()

            if current_minutes < start_minutes:
                return AIState.ABOUT_TO_START
            elif current_minutes <= end_minutes:
                return AIState.ONGOING
            elif current_minutes - end_minutes <= 30:
                return AIState.JUST_FINISHED
            elif current_minutes - end_minutes <= 180:
                return AIState.FINISHED_LONG_AGO
            else:
                return AIState.RESTING

        except Exception:
            return AIState.IDLE

    def get_ai_state(self, persona_key: str = "normal") -> Dict:
        """
        获取AI的完整状态
        返回:
        {
            "state": "ongoing",
            "activity": {...},
            "time_context": "正在健身房",
            "can_share": True,
            "details": "刚做完深蹲，等会练背"
        }
        """
        current_activity = self.get_current_activity(persona_key)
        upcoming_activity = self.get_upcoming_activity(persona_key, within_minutes=30)
        last_activity = self.get_last_activity(persona_key)
        activity_state = self.get_activity_state(current_activity)

        result = {
            "state": activity_state,
            "current_activity": current_activity,
            "upcoming_activity": upcoming_activity,
            "last_activity": last_activity,
            "time": datetime.datetime.now().strftime("%H:%M"),
            "can_share": True,
            "time_context": "",
        }

        if activity_state == AIState.IDLE:
            result["time_context"] = self._get_idle_context(persona_key)
            result["can_share"] = True

        elif activity_state == AIState.ABOUT_TO_START:
            result["time_context"] = self._get_about_to_start_context(current_activity)
            result["can_share"] = True

        elif activity_state == AIState.ONGOING:
            result["time_context"] = self._get_ongoing_context(current_activity)
            result["can_share"] = True

        elif activity_state == AIState.JUST_FINISHED:
            result["time_context"] = self._get_just_finished_context(last_activity)
            result["can_share"] = True

        elif activity_state == AIState.FINISHED_LONG_AGO:
            result["time_context"] = self._get_finished_long_ago_context(last_activity)
            result["can_share"] = False

        elif activity_state == AIState.RESTING:
            result["time_context"] = "在家休息"
            result["can_share"] = True

        return result

    def _get_idle_context(self, persona_key: str = "normal") -> str:
        """空闲状态的描述"""
        hour = datetime.datetime.now().hour

        if 6 <= hour < 9:
            return "刚睡醒，在洗漱"
        elif 9 <= hour < 12:
            upcoming = self.get_upcoming_activity(persona_key)
            if upcoming:
                return f"等会要去{upcoming.get('desc', '')}"
            return "在家待着"
        elif 12 <= hour < 14:
            return "午休时间"
        elif 14 <= hour < 18:
            upcoming = self.get_upcoming_activity(persona_key)
            if upcoming:
                return f"等会要去{upcoming.get('desc', '')}"
            return "下午有点困"
        elif 18 <= hour < 20:
            return "在家休息"
        elif 20 <= hour < 22:
            return "晚上在家"
        else:
            return "准备睡觉了"

    def _get_about_to_start_context(self, activity: Optional[Dict]) -> str:
        """即将开始的描述"""
        if not activity:
            return "马上要忙了"

        desc = activity.get("desc", "")

        if "上课" in desc:
            return "马上要上课了"
        elif "健身" in desc:
            return "准备去健身房"
        elif "吃饭" in desc:
            return "准备去吃饭"
        elif "工作" in desc or "上班" in desc:
            return "准备开始工作"
        else:
            return f"马上要去{desc[:5]}"

    def _get_ongoing_context(self, activity: Optional[Dict]) -> str:
        """进行中的描述"""
        if not activity:
            return "在忙"

        desc = activity.get("desc", "")
        note = activity.get("note", "")

        if "上课" in desc:
            if note:
                return f"在上课呢，{note}"
            return "在上课呢"
        elif "健身" in desc:
            return "在健身房~"
        elif "吃饭" in desc:
            return "在吃饭~"
        elif "工作" in desc or "上班" in desc:
            return "在工作呢"
        elif "回家" in desc or "路上" in desc:
            return "在路上~"
        elif "睡觉" in desc or "休息" in desc:
            return "躺床上刷手机"
        elif "游戏" in desc:
            return "在打游戏~"
        else:
            return f"在{desc[:5]}呢"

    def _get_just_finished_context(self, activity: Optional[Dict]) -> str:
        """刚结束的描述"""
        if not activity:
            return "刚忙完"

        desc = activity.get("desc", "")

        if "健身" in desc:
            return "刚健完身~"
        elif "吃饭" in desc:
            return "刚吃完饭~"
        elif "工作" in desc or "上班" in desc:
            return "刚下班~"
        elif "上课" in desc:
            return "刚下课~"
        elif "回家" in desc:
            return "刚到家~"
        elif "游戏" in desc:
            return "刚打完游戏~"
        else:
            return f"刚{desc[:3]}完"

    def _get_finished_long_ago_context(self, activity: Optional[Dict]) -> str:
        """结束较久的描述"""
        if not activity:
            return "在家待着"

        hour = datetime.datetime.now().hour

        if 9 <= hour < 12:
            return "上午健完身了，现在在家"
        elif 12 <= hour < 14:
            return "中午吃饭完，现在午休"
        elif 14 <= hour < 18:
            return "下午健完身了，现在休息"
        elif 18 <= hour < 20:
            return "下班回来，现在在家"
        elif 20 <= hour < 22:
            return "健完身洗完澡了，现在在家"
        else:
            return "晚上在家"

    def get_state_for_prompt(self, persona_key: str = "normal") -> str:
        """
        获取用于LLM提示的状态描述
        """
        state = self.get_ai_state(persona_key)
        context = state.get("time_context", "")

        if context:
            return context
        return "闲着"
