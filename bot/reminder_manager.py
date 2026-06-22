"""
定时提醒管理器
支持短期/长期/每日重复提醒，配合 GPT-SoVITS 语音提醒
"""

import os
import re
import time
import json
import threading
import yaml
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from threading import Timer, Lock
from loguru import logger

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 语音 TTS 已移除
def speak_reminder(text, use_gpt_sovits=True):
    logger.warning("[TTS] 语音提醒功能已被移除")
    return False


class ReminderManager:
    """定时提醒管理器"""

    def __init__(self, bot_instance, config_path: str = None):
        self.bot = bot_instance
        self.data_dir = PROJECT_ROOT
        self.data_file = os.path.join(self.data_dir, "reminders_data.json")
        self.config_file = config_path or os.path.join(self.data_dir, "reminder_config.yaml")

        self.reminders: List[Dict] = []
        self.active_timers: Dict[str, Timer] = {}
        self.monitor_thread: threading.Thread = None
        self.running = False
        self.timer_lock = Lock()
        self.next_short_id = 0
        self._user_id_to_name: Dict[str, str] = {}

        self.config = self._load_config()
        self._load()
        self._schedule_all()

    def _load_config(self) -> Dict:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"[提醒] 配置文件加载失败: {e}")
        return {"reminder": {"enabled": True, "keywords": [], "voice": {}, "quiet_hours": {}}}

    @property
    def enabled(self) -> bool:
        return self.config.get("reminder", {}).get("enabled", True)

    @property
    def keywords(self) -> List[str]:
        return self.config.get("reminder", {}).get(
            "keywords", ["提醒", "提醒我", "定时", "分钟后", "小时后", "叫我", "每天"]
        )

    @property
    def voice_enabled(self) -> bool:
        return self.config.get("reminder", {}).get("voice", {}).get("enabled", True)

    def is_reminder_request(self, message: str) -> bool:
        """检测是否是提醒请求"""
        if not self.enabled:
            return False
        return any(kw in message for kw in self.keywords)

    def is_quiet_hours(self) -> bool:
        """检查是否在安静时间内"""
        quiet = self.config.get("reminder", {}).get("quiet_hours", {})
        if not quiet:
            return False

        now = datetime.now()
        start = quiet.get("start", "22:00")
        end = quiet.get("end", "08:00")

        start_hour, start_min = map(int, start.split(":"))
        end_hour, end_min = map(int, end.split(":"))

        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min

        if start_minutes > end_minutes:
            return current_minutes >= start_minutes or current_minutes < end_minutes
        else:
            return start_minutes <= current_minutes < end_minutes

    def set_short_reminder(
        self, user_id: str, user_name: str, delay_seconds: int, content: str
    ) -> str:
        """设置短期提醒 (≤10分钟)，返回定时器ID"""
        timer_id = f"short_{self.next_short_id}"
        self.next_short_id += 1

        if user_name:
            self._user_id_to_name[user_id] = user_name

        with self.timer_lock:
            timer = Timer(
                float(delay_seconds),
                self._trigger_reminder,
                args=[user_id, user_name, timer_id, content],
            )
            self.active_timers[timer_id] = timer
            timer.start()

        logger.info(f"[提醒] 已设置 {delay_seconds}秒后提醒: {content}")
        return timer_id

    def set_long_reminder(
        self, user_id: str, user_name: str, target_time: datetime, content: str
    ) -> Dict:
        """设置长期提醒 (>10分钟)"""
        if user_name:
            self._user_id_to_name[user_id] = user_name

        reminder = {
            "type": "one-off",
            "id": f"long_{int(time.time() * 1000)}",
            "user_id": user_id,
            "user_name": user_name,
            "target_time": target_time.isoformat(),
            "content": content,
            "triggered": False,
        }
        self.reminders.append(reminder)
        self._save()
        logger.info(f"[提醒] 已设置长期提醒 {target_time}: {content}")
        return reminder

    def set_recurring_reminder(
        self, user_id: str, user_name: str, time_str: str, content: str
    ) -> Dict:
        """设置每日重复提醒"""
        if user_name:
            self._user_id_to_name[user_id] = user_name

        reminder = {
            "type": "recurring",
            "id": f"recurring_{int(time.time() * 1000)}",
            "user_id": user_id,
            "user_name": user_name,
            "time_str": time_str,
            "content": content,
        }
        self.reminders.append(reminder)
        self._save()
        logger.info(f"[提醒] 已设置每日提醒 {time_str}: {content}")
        return reminder

    def _trigger_reminder(self, user_id: str, user_name: str, timer_id: str, content: str):
        """触发提醒 (短期)"""
        logger.info(f"[提醒] 触发短期提醒: {content}")

        with self.timer_lock:
            if timer_id in self.active_timers:
                del self.active_timers[timer_id]

        chat_name = user_name or self._user_id_to_name.get(user_id, user_id)
        self._notify_user(chat_name, content)

    def _notify_user(self, chat_name: str, content: str):
        """通知用户"""
        if self.is_quiet_hours():
            logger.info("[提醒] 安静时间内，跳过通知")
            return

        try:
            reminder_text = f"🔔 提醒时间到：{content}"
            self.bot.send_message(reminder_text, chat_name=chat_name)
            logger.info(f"[提醒] 已发送微信提醒: {content}")

            if self.voice_enabled:
                voice_text = f"{content}时间到了"
                threading.Thread(
                    target=speak_reminder, args=(voice_text, True), daemon=True
                ).start()
                logger.info("[提醒] 已触发语音提醒")

        except Exception as e:
            logger.error(f"[提醒] 发送提醒失败: {e}")

    def _schedule_all(self):
        """加载所有提醒并启动监控"""
        self._start_monitor_thread()

    def _start_monitor_thread(self):
        """启动后台监控线程"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("[提醒] 后台监控线程已启动")

    def _monitor_loop(self):
        """监控循环 - 检查长期和每日提醒"""
        while self.running:
            try:
                now = datetime.now()
                reminders_to_remove = []

                with self.timer_lock:
                    for reminder in self.reminders:
                        reminder_type = reminder.get("type")

                        if reminder_type == "one-off" and not reminder.get("triggered"):
                            target_time = datetime.fromisoformat(reminder["target_time"])
                            if now >= target_time:
                                user_id = reminder["user_id"]
                                user_name = reminder.get("user_name")
                                content = reminder["content"]
                                reminder["triggered"] = True
                                reminders_to_remove.append(reminder["id"])
                                chat_name = user_name or self._user_id_to_name.get(user_id, user_id)
                                self._notify_user(chat_name, content)

                        elif reminder_type == "recurring":
                            time_str = reminder["time_str"]
                            hour, minute = map(int, time_str.split(":"))

                            if now.hour == hour and now.minute == minute and now.second < 5:
                                user_id = reminder["user_id"]
                                user_name = reminder.get("user_name")
                                content = reminder["content"]
                                chat_name = user_name or self._user_id_to_name.get(user_id, user_id)
                                self._notify_user(chat_name, content)

                if reminders_to_remove:
                    self.reminders = [
                        r for r in self.reminders if r.get("id") not in reminders_to_remove
                    ]
                    self._save()

            except Exception as e:
                logger.error(f"[提醒] 监控循环异常: {e}")

            time.sleep(1)

    def parse_with_ai(self, message: str, lm_client) -> Optional[Dict]:
        """使用 AI 解析提醒请求"""
        now = datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %A %H:%M:%S")

        parsing_prompt = f"""当前时间是: {current_time_str}
用户消息: "{message}"

请判断这是否是提醒请求，并提取信息：

类型判断:
- A) 短期一次性 (≤10分钟): "5分钟后提醒我喝水"
- B) 长期一次性 (>10分钟): "1小时后开会"、"明早7点叫我"
- C) 每日重复: "每天早上8点起床"
- D) 非提醒: "今天天气怎样"

输出格式:
- 提醒: {{"type": "short|long|recurring", "delay_seconds": 300, "time_str": "08:00", "target_time": "2026-04-03 15:30", "content": "喝水"}}
- 非提醒: null

请务必严格遵守输出格式，只返回 JSON 对象或 null。"""

        try:
            response = lm_client.chat([{"role": "user", "content": parsing_prompt}])

            if isinstance(response, str):
                response_text = response
            elif isinstance(response, dict):
                response_text = response.get("content", "") or response.get("message", "")
            else:
                response_text = str(response)

            import json as json_module

            response_text = re.sub(r"```json\n?|\n?```", "", response_text).strip()

            if response_text == "null":
                return None

            result = json_module.loads(response_text)
            return result

        except Exception as e:
            logger.error(f"[提醒] AI解析失败: {e}")
            return self._quick_parse(message)

    def _quick_parse(self, message: str) -> Optional[Dict]:
        """快速正则解析 (备选方案)"""
        message = message.strip()

        patterns = [
            (r"(\d+)\s*(?:分|分钟).*?提醒.*?(.+)", "short", lambda m: int(m.group(1)) * 60),
            (r"(\d+)\s*(?:秒|秒钟).*?提醒.*?(.+)", "short", lambda m: int(m.group(1))),
            (
                r"(\d+)\s*(?:小时|钟头).*?提醒.*?(.+)",
                "long",
                lambda m: datetime.now() + timedelta(hours=int(m.group(1))),
            ),
            (
                r"每天\s*(\d{1,2}):(\d{2}).*?提醒.*?(.+)",
                "recurring",
                lambda m: f"{m.group(1)}:{m.group(2)}",
            ),
            (
                r"(\d{1,2}):(\d{2}).*?提醒.*?(.+)",
                "long",
                lambda m: datetime.now().replace(
                    hour=int(m.group(1)), minute=int(m.group(2)), second=0
                ),
            ),
        ]

        for pattern, rtype, extractor in patterns:
            match = re.search(pattern, message)
            if match:
                if rtype == "short":
                    return {
                        "type": "short",
                        "delay_seconds": extractor(match),
                        "content": match.group(2).strip(),
                    }
                elif rtype == "long":
                    result = extractor(match)
                    if isinstance(result, datetime):
                        return {
                            "type": "long",
                            "target_time": result.isoformat(),
                            "content": match.group(3).strip(),
                        }
                    else:
                        return {
                            "type": "long",
                            "target_time": result,
                            "content": match.group(3).strip(),
                        }
                elif rtype == "recurring":
                    return {
                        "type": "recurring",
                        "time_str": extractor(match),
                        "content": match.group(3).strip(),
                    }

        return None

    def handle_reminder_request(
        self, message: str, user_id: str, user_name: str = None
    ) -> Optional[str]:
        """处理提醒请求，返回确认消息"""
        if not self.enabled:
            return None

        if user_name:
            self._user_id_to_name[user_id] = user_name

        parsed = self.parse_with_ai(message, self.bot.lm_client)

        if parsed is None:
            return None

        rtype = parsed.get("type")
        content = parsed.get("content", "").strip()

        if not content:
            return "嗯...光设置时间还不行，得告诉我你要提醒做什么呀？"

        if rtype == "short":
            delay = parsed.get("delay_seconds", 0)
            if delay <= 0 or delay > 600:
                return None
            self.set_short_reminder(user_id, user_name, delay, content)
            delay_min = delay // 60 if delay >= 60 else 1
            return f"好！{delay_min}分钟后提醒你：{content}"

        elif rtype == "long":
            target_time_str = parsed.get("target_time")
            if target_time_str:
                target_time = datetime.fromisoformat(target_time_str)
            else:
                time_str = parsed.get("time_str", "")
                if time_str:
                    parts = time_str.split(":")
                    target_time = datetime.now().replace(
                        hour=int(parts[0]), minute=int(parts[1]), second=0
                    )
                    if target_time < datetime.now():
                        target_time += timedelta(days=1)
                else:
                    return None

            self.set_long_reminder(user_id, user_name, target_time, content)
            friendly_time = target_time.strftime("%m月%d日 %H:%M")
            return f"好的！{friendly_time}提醒你：{content}"

        elif rtype == "recurring":
            time_str = parsed.get("time_str")
            if time_str:
                self.set_recurring_reminder(user_id, user_name, time_str, content)
                return f"没问题！每天 {time_str} 提醒你：{content}"

        return None

    def _save(self):
        """保存提醒数据到文件"""
        try:
            data = {"reminders": self.reminders}
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[提醒] 保存提醒数据失败: {e}")

    def _load(self):
        """加载提醒数据"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.reminders = data.get("reminders", [])

                    self.reminders = [
                        r
                        for r in self.reminders
                        if r.get("type") == "recurring" or not r.get("triggered", False)
                    ]

                    logger.info(f"[提醒] 已加载 {len(self.reminders)} 条历史提醒")
        except Exception as e:
            logger.error(f"[提醒] 加载提醒数据失败: {e}")
            self.reminders = []

    def shutdown(self):
        """关闭提醒管理器"""
        self.running = False

        with self.timer_lock:
            for timer in self.active_timers.values():
                timer.cancel()
            self.active_timers.clear()

        self._save()
        logger.info("[提醒] 提醒管理器已关闭")


if __name__ == "__main__":

    class MockBot:
        def __init__(self):
            self.lm_client = None

        def send_message(self, content, chat_name=""):
            print(f"[模拟发送消息] {chat_name}: {content}")

    bot = MockBot()
    manager = ReminderManager(bot)

    print("定时提醒管理器测试")
    print(f"配置文件: {manager.config_file}")
    print(f"数据文件: {manager.data_file}")
    print(f"功能启用: {manager.enabled}")
    print(f"唤醒词: {manager.keywords[:5]}...")

    result = manager._quick_parse("5分钟后提醒我喝水")
    print(f"快速解析结果: {result}")

    result = manager.handle_reminder_request("5分钟后提醒我喝水", "测试用户")
    print(f"处理结果: {result}")

    manager.shutdown()
