import os
import json
import datetime
import logging
import re
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

try:
    import holidays

    CHINESE_HOLIDAYS = holidays.China(years=datetime.datetime.now().year)
except ImportError:
    CHINESE_HOLIDAYS = {}


class ScheduleManager:
    SCHEDULE_DIR = os.path.join("data", "schedules")
    PERSONA_DIR_PREFIX = "persona_"

    DEFAULT_PERSONA = {
        "key": "normal",
        "name": "默认角色",
        "description": "自信阳光的22岁男生",
        "schedule_preferences": {
            "wake_time_range": (7, 9),
            "sleep_time_range": (22, 24),
            "hobbies": ["健身", "看电影", "和朋友聚会"],
            "work_style": "普通上班族",
            "social_level": "中等",
            "exercise_frequency": "偶尔健身",
        },
    }

    PERSONA_SCHEDULE_STYLES = {
        "normal": {
            "description": "自信阳光的22岁男生",
            "wake_time_range": (7, 9),
            "sleep_time_range": (22, 24),
            "hobbies": ["健身", "看电影", "和朋友聚会"],
            "work_style": "普通上班族",
            "social_level": "中等",
            "exercise_frequency": "偶尔健身",
            "meal_style": "家常菜为主，偶尔外卖",
        },
        "S": {
            "description": "掌控者，强势直接",
            "wake_time_range": (6, 8),
            "sleep_time_range": (23, 1),
            "hobbies": ["阅读", "健身", "品酒", "高尔夫"],
            "work_style": "管理层，工作繁忙",
            "social_level": "高",
            "exercise_frequency": "经常健身",
            "meal_style": "精致餐厅，偶尔在家做饭",
        },
        "MM": {
            "description": "温柔体贴的女生",
            "wake_time_range": (7, 9),
            "sleep_time_range": (22, 23),
            "hobbies": ["追剧", "逛街", "美容", "瑜伽"],
            "work_style": "普通上班族或学生",
            "social_level": "高",
            "exercise_frequency": "偶尔瑜伽或散步",
            "meal_style": "注重健康，喜欢轻食和甜点",
        },
    }

    def __init__(self, lm_client=None, persona_prefs: Dict = None):
        self.lm_client = lm_client
        os.makedirs(self.SCHEDULE_DIR, exist_ok=True)
        self.persona_prefs = persona_prefs or self.DEFAULT_PERSONA

    def _get_persona_style(self, persona_info: Dict = None) -> Dict:
        persona = persona_info or self.persona_prefs
        persona_key = persona.get("key", "normal")

        if persona.get("schedule_preferences"):
            prefs = persona["schedule_preferences"]
            return {
                "description": persona.get("description", ""),
                "wake_time_range": tuple(prefs.get("wake_time_range", [7, 9])),
                "sleep_time_range": tuple(prefs.get("sleep_time_range", [22, 24])),
                "hobbies": prefs.get("hobbies", ["看电影"]),
                "work_style": prefs.get("work_style", "普通上班族"),
                "social_level": prefs.get("social_level", "中等"),
                "exercise_frequency": prefs.get("exercise_frequency", "偶尔运动"),
                "meal_style": prefs.get("meal_style", "家常菜为主"),
            }

        return self.PERSONA_SCHEDULE_STYLES.get(persona_key, self.PERSONA_SCHEDULE_STYLES["normal"])

    def _lm_chat_json(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
        retry_times: int = 2,
        required_fields: list = None,
    ) -> Optional[Dict]:
        """通用 LM Chat + JSON 解析，支持重试和完整性检查"""
        if not self.lm_client:
            return None

        last_error = None
        required_fields = required_fields or []

        for attempt in range(retry_times + 1):
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
                        data = json.loads(json_match.group())

                        # 检查必需字段
                        if required_fields:
                            missing_fields = [f for f in required_fields if f not in data]
                            if missing_fields:
                                logger.warning(
                                    f"JSON 缺少必需字段（第{attempt + 1}次）：{missing_fields}，字符数={len(json_match.group())}"
                                )
                                last_error = ValueError(f"缺少字段: {missing_fields}")
                                if attempt < retry_times:
                                    time.sleep(2)  # 等待更长时间让LLM完成输出
                                    continue
                                return data  # 返回不完整的也总比没有好

                        return data
                    else:
                        logger.warning(f"JSON 提取失败（第{attempt + 1}次）：响应中未找到 JSON")
                        last_error = ValueError("未找到有效的 JSON 格式")
            except json.JSONDecodeError as e:
                logger.warning(f"JSON 解析失败（第{attempt + 1}次）：{e}")
                last_error = e
            except ConnectionError as e:
                logger.warning(f"连接失败（第{attempt + 1}次）：{e}")
                last_error = e
            except TimeoutError as e:
                logger.warning(f"请求超时（第{attempt + 1}次）：{e}")
                last_error = e
            except Exception as e:
                logger.error(f"未知错误（第{attempt + 1}次）：{e}")
                last_error = e

            if attempt < retry_times:
                time.sleep(1)

        if last_error:
            logger.error(f"LM Chat 失败，已重试 {retry_times} 次：{last_error}")
        return None

    def _get_week_start(self, date: datetime.date) -> datetime.date:
        return date - datetime.timedelta(days=date.weekday())

    def _get_persona_schedule_dir(self, persona_key: str = "normal") -> str:
        if persona_key == "normal":
            return self.SCHEDULE_DIR
        return os.path.join(self.SCHEDULE_DIR, f"{self.PERSONA_DIR_PREFIX}{persona_key}")

    def _get_week_file(self, week_start: datetime.date, persona_key: str = "normal") -> str:
        persona_dir = self._get_persona_schedule_dir(persona_key)
        return os.path.join(persona_dir, f"weekly_{week_start.isoformat()}.json")

    def _get_daily_file(self, date: datetime.date, persona_key: str = "normal") -> str:
        persona_dir = self._get_persona_schedule_dir(persona_key)
        return os.path.join(persona_dir, f"daily_{date.isoformat()}.json")

    def _is_holiday(self, date: datetime.date) -> Optional[str]:
        if date in CHINESE_HOLIDAYS:
            return CHINESE_HOLIDAYS[date]
        if date.weekday() >= 5:
            return "周末"
        return None

    def _get_chinese_weekday(self, date: datetime.date) -> str:
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return weekdays[date.weekday()]

    def get_current_schedule(self, persona_key: str = "normal") -> Dict:
        today = datetime.date.today()
        week_start = self._get_week_start(today)
        daily_file = self._get_daily_file(today, persona_key)

        schedule = {
            "today": today.isoformat(),
            "weekday": self._get_chinese_weekday(today),
            "holiday": self._is_holiday(today),
            "daily_plan": None,
            "weekly_plan": None,
            "persona": persona_key,
        }

        if os.path.exists(daily_file):
            with open(daily_file, "r", encoding="utf-8") as f:
                schedule["daily_plan"] = json.load(f)

        weekly_file = self._get_week_file(week_start, persona_key)
        if os.path.exists(weekly_file):
            with open(weekly_file, "r", encoding="utf-8") as f:
                schedule["weekly_plan"] = json.load(f)

        return schedule

    def _should_regenerate_weekly(
        self, week_start: datetime.date, persona_key: str = "normal"
    ) -> bool:
        week_file = self._get_week_file(week_start, persona_key)
        if not os.path.exists(week_file):
            return True
        file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(week_file))
        return (datetime.datetime.now() - file_mtime).days >= 7

    def _should_regenerate_daily(self, date: datetime.date, persona_key: str = "normal") -> bool:
        daily_file = self._get_daily_file(date, persona_key)
        return not os.path.exists(daily_file)

    def _generate_weekly_schedule(
        self, week_start: datetime.date, persona_info: Dict = None, persona_key: str = "normal"
    ) -> Dict:
        today = datetime.date.today()
        persona = persona_info or self.persona_prefs
        if not persona_info:
            persona["key"] = persona_key
        persona_key = persona.get("key", "normal")
        persona_style = self._get_persona_style(persona)

        persona_context = f"""【角色信息】
角色设定：{persona_style['description']}
工作/学习方式：{persona_style['work_style']}
兴趣爱好：{', '.join(persona_style['hobbies'])}
社交活跃度：{persona_style['social_level']}
运动习惯：{persona_style['exercise_frequency']}
饮食偏好：{persona_style['meal_style']}"""

        prompt = f"""请根据以下角色信息生成一周的简略日程安排。

{persona_context}

当前日期: {today.isoformat()} {self._get_chinese_weekday(today)}
周计划开始日期: {week_start.isoformat()} ({self._get_chinese_weekday(week_start)})

请生成周一到周日的简略日程安排，每天的计划用一句话概括。
日程安排要贴合角色特点，符合其身份、爱好和生活习惯。

请按以下JSON格式输出，不要输出其他内容：
{{
    "week_start": "{week_start.isoformat()}",
    "persona": "{persona_key}",
    "weekday_summary": {{
        "Monday": "上班/工作",
        "Tuesday": "下班后健身",
        "Wednesday": "上班/工作",
        "Thursday": "和朋友聚会",
        "Friday": "下班后逛街",
        "Saturday": "睡懒觉，看电影",
        "Sunday": "准备下周工作"
    }}
}}"""

        schedule = self._lm_chat_json(prompt, max_tokens=500, temperature=0.7)
        if schedule:
            if "persona" not in schedule:
                schedule["persona"] = persona_key
            self._save_weekly_schedule(week_start, schedule, persona_key)
            return schedule

        logger.warning("生成周计划失败，使用默认计划")
        return self._generate_default_weekly_schedule(week_start, persona_key)

    def _generate_default_weekly_schedule(
        self, week_start: datetime.date, persona_key: str = "normal"
    ) -> Dict:
        default_schedule = {
            "Monday": "上班/上学",
            "Tuesday": "下班后健身",
            "Wednesday": "上班/上学",
            "Thursday": "和朋友视频聊天",
            "Friday": "下班后逛街吃饭",
            "Saturday": "睡懒觉，追剧放松",
            "Sunday": "整理房间，准备下周",
        }
        schedule = {
            "week_start": week_start.isoformat(),
            "persona": persona_key,
            "weekday_summary": default_schedule,
        }
        self._save_weekly_schedule(week_start, schedule, persona_key)
        return schedule

    def _save_weekly_schedule(
        self, week_start: datetime.date, schedule: Dict, persona_key: str = "normal"
    ):
        week_file = self._get_week_file(week_start, persona_key)
        os.makedirs(os.path.dirname(week_file), exist_ok=True)
        with open(week_file, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)

    def _generate_daily_schedule(
        self,
        date: datetime.date,
        weekly_plan: Dict,
        persona_info: Dict = None,
        persona_key: str = "normal",
    ) -> Dict:
        today = datetime.date.today()
        weekday = self._get_chinese_weekday(date)
        weekday_key = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ][date.weekday()]
        base_plan = weekly_plan.get("weekday_summary", {}).get(weekday_key, "在家休息")
        holiday_info = self._is_holiday(date)

        persona = persona_info or self.persona_prefs
        if not persona_info:
            persona["key"] = persona_key
        persona_key = persona.get("key", "normal")
        persona_style = self._get_persona_style(persona)

        persona_context = f"""【角色信息】
角色设定：{persona_style['description']}
工作/学习方式：{persona_style['work_style']}
兴趣爱好：{', '.join(persona_style['hobbies'])}
社交活跃度：{persona_style['social_level']}
运动习惯：{persona_style['exercise_frequency']}
饮食偏好：{persona_style['meal_style']}"""

        wake_start, wake_end = persona_style["wake_time_range"]
        sleep_start, sleep_end = persona_style["sleep_time_range"]

        prompt = f"""请根据角色信息和周计划生成 {date.isoformat()}（{weekday}）的详细日程。

{persona_context}

{"今天是节假日：" + holiday_info if holiday_info else f"今天是{today.isoformat()}（{self._get_chinese_weekday(today)}）"}

周计划安排：{base_plan}

请生成这个角色的一天详细日程，包含：
1. 起床时间（建议 {wake_start}-{wake_end} 点）
2. 早餐/午餐/晚餐的大概安排（根据饮食偏好）
3. 上午/下午/晚上的主要活动（结合兴趣爱好和社交活跃度）
4. 睡前活动

重要：每个活动必须标注是否可以在做这件事的时候聊天。

【聊天可行性标注规则】
- can_chat: true = 可以边做边聊，不影响活动
  例：吃饭、休息、健身、回家路上、逛街、刷手机
- can_chat: false = 需要专注，不方便边做边聊
  例：上课（重要）、开会、考试、写作业、打游戏（团战）、做实验

【具体示例】
- "在公司开会" → can_chat: false（需要专注）
- "在水课上摸鱼" → can_chat: true（反正也是闲着）
- "健身" → can_chat: true（可以边健身边聊）
- "写作业" → can_chat: false（需要专注思考）
- "吃饭" → can_chat: true（边吃边聊很正常）
- "刷视频休息" → can_chat: true（随时可以停下）

请按以下JSON格式输出，不要输出其他内容：
{{
    "date": "{date.isoformat()}",
    "weekday": "{weekday}",
    "persona": "{persona_key}",
    "holiday": {json.dumps(holiday_info) if holiday_info else "null"},
    "base_plan": "{base_plan}",
    "wake_time": "{wake_start}:30",
    "meals": {{
        "breakfast": "路边买包子豆浆，边走边吃去上班",
        "lunch": "公司附近快餐，12点吃饭",
        "dinner": "下班路上买菜回家做饭"
    }},
    "activities": [
        {{"time": "09:00-12:00", "desc": "上班工作，处理日常事务", "can_chat": false, "note": "需要专注"}},
        {{"time": "12:00-13:30", "desc": "午休，饭后刷会儿手机", "can_chat": true}},
        {{"time": "14:00-18:00", "desc": "继续工作，开了个会", "can_chat": false, "note": "重要会议"}},
        {{"time": "18:30-19:30", "desc": "下班回家，路上听音乐", "can_chat": true}},
        {{"time": "20:00-22:00", "desc": "看看剧放松一下", "can_chat": true}},
        {{"time": "23:00", "desc": "准备睡觉，躺在床上刷手机", "can_chat": true}}
    ],
    "notes": "今天工作有点累，但心情还不错"
}}"""

        schedule = self._lm_chat_json(
            prompt, max_tokens=1500, temperature=0.8, required_fields=["activities", "wake_time"]
        )
        if schedule:
            self._save_daily_schedule(date, schedule, persona_key)
            return schedule

        logger.warning("生成日计划失败，使用默认计划")
        return self._generate_default_daily_schedule(date, base_plan, persona_key)

    def _generate_default_daily_schedule(
        self, date: datetime.date, base_plan: str, persona_key: str = "normal"
    ) -> Dict:
        schedule = {
            "date": date.isoformat(),
            "weekday": self._get_chinese_weekday(date),
            "holiday": self._is_holiday(date),
            "base_plan": base_plan,
            "wake_time": "08:00",
            "meals": {"breakfast": "在家吃", "lunch": "外卖", "dinner": "回家做饭"},
            "activities": [
                {"time": "09:00-12:00", "desc": "上班/上学", "can_chat": False, "note": "需要专注"},
                {"time": "12:00-14:00", "desc": "午休", "can_chat": True},
                {
                    "time": "14:00-18:00",
                    "desc": "下午工作/学习",
                    "can_chat": False,
                    "note": "需要专注",
                },
                {"time": "18:00", "desc": "下班/放学回家", "can_chat": True},
            ],
            "notes": "普通的一天",
        }
        self._save_daily_schedule(date, schedule, persona_key)
        return schedule

    def _save_daily_schedule(
        self, date: datetime.date, schedule: Dict, persona_key: str = "normal"
    ):
        daily_file = self._get_daily_file(date, persona_key)
        os.makedirs(os.path.dirname(daily_file), exist_ok=True)
        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)

    def ensure_today_schedule(self, persona_info: Dict = None, persona_key: str = "normal") -> Dict:
        today = datetime.date.today()
        week_start = self._get_week_start(today)

        persona = persona_info or self.persona_prefs
        if not persona_info:
            persona["key"] = persona_key

        os.makedirs(self._get_persona_schedule_dir(persona_key), exist_ok=True)

        if self._should_regenerate_weekly(week_start, persona_key):
            self._generate_weekly_schedule(week_start, persona, persona_key)

        weekly_file = self._get_week_file(week_start, persona_key)
        with open(weekly_file, "r", encoding="utf-8") as f:
            weekly_plan = json.load(f)

        if weekly_plan.get("persona") != persona_key or self._should_regenerate_daily(
            today, persona_key
        ):
            self._generate_daily_schedule(today, weekly_plan, persona, persona_key)

        return self.get_current_schedule(persona_key)

    def format_schedule_for_ai(self, schedule: Dict) -> str:
        now = datetime.datetime.now()
        current_hour = now.hour
        current_minute = now.minute

        parts = []
        parts.append(
            f"【当前时间】{schedule['today']} {schedule['weekday']} {current_hour}:{current_minute:02d}"
        )
        if schedule.get("holiday"):
            parts.append(f"【节假日】{schedule['holiday']}")

        if schedule.get("daily_plan"):
            daily = schedule["daily_plan"]
            parts.append("\n【今日日程安排】")
            if daily.get("wake_time"):
                parts.append(f"起床时间: {daily['wake_time']}")
            if daily.get("meals"):
                meals = daily["meals"]
                parts.append(f"早餐安排: {meals.get('breakfast', '在家吃')}")
                parts.append(f"午餐安排: {meals.get('lunch', '外卖')}")
                parts.append(f"晚餐安排: {meals.get('dinner', '回家做饭')}")
            if daily.get("activities"):
                parts.append("今日活动安排:")
                for act in daily["activities"]:
                    start_time = act["time"].split("-")[0] if "-" in act["time"] else act["time"]
                    if ":" in start_time:
                        try:
                            act_hour = int(start_time.split(":")[0])
                            if act_hour < current_hour or (
                                act_hour == current_hour and current_minute >= 30
                            ):
                                status = "已完成"
                            else:
                                status = "待办"
                            parts.append(f"  {act['time']} [{status}] {act['desc']}")
                        except Exception:
                            parts.append(f"  {act['time']} - {act['desc']}")
                    else:
                        parts.append(f"  {act['time']} - {act['desc']}")
            if daily.get("notes"):
                parts.append(f"今日心情/状态: {daily['notes']}")

        return "\n".join(parts)

    def format_schedule_as_life(self, schedule: Dict, persona_name: str = "小明") -> str:
        """将日程转换为'AI的生活'风格 - 主观、随意的第一人称描述"""
        now = datetime.datetime.now()
        current_hour = now.hour
        current_minute = now.minute

        parts = []

        current_time_desc = f"{current_hour}:{current_minute:02d}"

        if 6 <= current_hour < 9:
            life_desc = "刚睡醒，在洗漱准备出门"
        elif 9 <= current_hour < 12:
            life_desc = "上班中，摸鱼ing"
        elif 12 <= current_hour < 14:
            life_desc = "午休，吃完饭犯困"
        elif 14 <= current_hour < 18:
            life_desc = "下午干活，有点困"
        elif 18 <= current_hour < 20:
            life_desc = "刚下班，在回家路上"
        elif 20 <= current_hour < 22:
            life_desc = "在家躺着，不想动"
        else:
            life_desc = "准备睡觉了，躺床上刷手机"

        parts.append(f"【{persona_name}现在 {current_time_desc}】{life_desc}")

        if schedule.get("daily_plan"):
            daily = schedule["daily_plan"]

            if daily.get("notes"):
                parts.append(f"\n今天感觉：{daily['notes']}")

            if daily.get("meals"):
                meals = daily["meals"]
                meal_parts = []
                if meals.get("breakfast"):
                    meal_parts.append(f"早:{meals['breakfast'][:10]}")
                if meals.get("lunch"):
                    meal_parts.append(f"午:{meals['lunch'][:10]}")
                if meals.get("dinner"):
                    meal_parts.append(f"晚:{meals['dinner'][:10]}")
                if meal_parts:
                    parts.append(f"今天吃了：{' '.join(meal_parts)}")

            activities = daily.get("activities", [])
            if activities:
                future_activities = []
                past_activities = []
                for act in activities:
                    start_time = (
                        act.get("time", "").split("-")[0]
                        if "-" in act.get("time", "")
                        else act.get("time", "")
                    )
                    if ":" in start_time:
                        try:
                            act_hour = int(start_time.split(":")[0])
                            if act_hour < current_hour or (
                                act_hour == current_hour and current_minute >= 30
                            ):
                                past_activities.append(act.get("desc", "")[:15])
                            else:
                                future_activities.append(act.get("desc", "")[:15])
                        except Exception:
                            pass

                if past_activities:
                    parts.append(f"今天干了：{past_activities[0]}")
                if future_activities:
                    parts.append(f"待会：{future_activities[0]}")

        if schedule.get("weekly_plan"):
            weekly = schedule["weekly_plan"]
            weekday_key = [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ][now.weekday()]
            today_plan = weekly.get("weekday_summary", {}).get(weekday_key, "")
            if today_plan and len(today_plan) > 5:
                parts.append(f"今天的基调：{today_plan[:20]}")

        return "\n".join(parts)

    def format_schedule_for_memory(self, schedule: Dict) -> str:
        """将日程格式化为适合写入语义记忆的文本"""
        if not schedule.get("daily_plan"):
            return ""

        daily = schedule["daily_plan"]
        parts = []

        if daily.get("wake_time"):
            parts.append(f"今天{daily['wake_time']}起床")

        if daily.get("meals"):
            meals = daily["meals"]
            if meals.get("breakfast"):
                parts.append(f"早餐：{meals['breakfast']}")
            if meals.get("lunch"):
                parts.append(f"午餐：{meals['lunch']}")
            if meals.get("dinner"):
                parts.append(f"晚餐：{meals['dinner']}")

        if daily.get("activities"):
            activities = daily["activities"]
            for act in activities[:4]:
                time_str = act.get("time", "")
                desc = act.get("desc", "")
                if time_str and desc:
                    parts.append(f"{time_str}：{desc}")

        if daily.get("notes"):
            parts.append(f"今天心情：{daily['notes']}")

        return "。".join(parts)

    def get_current_activity(self, persona_key: str = "normal") -> Optional[Dict]:
        """获取AI当前正在进行的活动"""
        now = datetime.datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        current_time_minutes = current_hour * 60 + current_minute

        schedule = self.get_current_schedule(persona_key)
        if not schedule.get("daily_plan"):
            return None

        activities = schedule["daily_plan"].get("activities", [])
        for act in activities:
            time_range = act.get("time", "")
            if "-" not in time_range:
                continue

            try:
                start_str, end_str = time_range.split("-")
                start_hour, start_min = map(
                    lambda x: (
                        int(x.replace(":", "")) // 100
                        if ":" in x
                        else int(x) if len(x) <= 2 else int(x[:2])
                    ),
                    [start_str, end_str],
                )

                if ":" in start_str:
                    start_parts = start_str.split(":")
                    start_hour = int(start_parts[0])
                    start_min = int(start_parts[1])
                else:
                    start_hour = int(start_str)
                    start_min = 0

                if ":" in end_str:
                    end_parts = end_str.split(":")
                    end_hour = int(end_parts[0])
                    end_min = int(end_parts[1])
                else:
                    end_hour = int(end_str)
                    end_min = 0

                start_time_minutes = start_hour * 60 + start_min
                end_time_minutes = end_hour * 60 + end_min

                if start_time_minutes <= current_time_minutes <= end_time_minutes:
                    return act
            except (ValueError, IndexError):
                continue

        return None

    def can_chat_now(self, persona_key: str = "normal") -> bool:
        """判断AI当前是否可以聊天"""
        activity = self.get_current_activity(persona_key)
        if not activity:
            return True
        return activity.get("can_chat", True)

    def get_current_activity_for_ai(self, persona_key: str = "normal") -> str:
        """获取AI当前活动的第一人称描述"""
        activity = self.get_current_activity(persona_key)
        if not activity:
            return "闲着"

        desc = activity.get("desc", "")
        can_chat = activity.get("can_chat", True)

        if "在" in desc or desc.startswith("准备"):
            return desc
        elif "上课" in desc:
            if can_chat:
                return "在水课上摸鱼呢~"
            return "在上课呢"
        elif "工作" in desc or "上班" in desc:
            return "在工作呢"
        elif "健身" in desc:
            return "在健身房~"
        elif "吃饭" in desc or "午饭" in desc or "晚餐" in desc or "早餐" in desc:
            return "在吃饭~"
        elif "回家" in desc:
            return "在回家路上~"
        elif "睡觉" in desc or "休息" in desc:
            return "躺床上刷手机"
        elif "游戏" in desc:
            return "在打游戏~"
        else:
            return f"在{desc}"

    def get_random_free_moment(self) -> Optional[Dict]:
        """获取一个随机的空闲时刻，用于主动发消息"""
        schedule = self.get_current_schedule()
        if not schedule.get("daily_plan"):
            return None

        activities = schedule["daily_plan"].get("activities", [])
        free_activities = [a for a in activities if a.get("can_chat", True)]

        if not free_activities:
            return None

        import random

        return random.choice(free_activities)
