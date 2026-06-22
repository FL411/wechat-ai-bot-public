"""
智能主动消息管理系统 v2
核心思路：化繁为简
1. 定时时间到 → 直接发消息（不判断）
2. 用户回复 → LLM理解语义 → 自然回应
3. 对话结束：用户不回复超X分钟 或 明确表示忙
"""

import os
import json
import random
import logging
import threading
import time
import datetime
from typing import Dict, List

from schedule.state_analyzer import StateAnalyzer

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_V2 = {
    "global": {
        "quiet_hours": {"start": "02:00", "end": "06:00"},
        "check_interval_seconds": 300,
        "auto_reply_enabled": True,
    },
    "girlfriend": {
        "enabled": True,
        "users": [],
        "messages": {
            "morning": ["早安呀~睡得好吗", "早~"],
            "night_ask": ["你睡了吗？好梦~", "准备休息了吗~"],
            "free_concern": ["在干嘛呀~", "想你了呢~", "在忙什么呀~"],
        },
    },
    "avatar": {"enabled": False, "users": []},
}


class ProactiveUserManagerV2:
    def __init__(self, bot=None, config_file: str = "data/proactive_users_v2.json"):
        self.bot = bot
        self.config_file = config_file
        self.config = self._load_config()

        logger.info(
            f"[主动消息V2] 初始化中... config类型: {type(self.config)}, config_file: {config_file}"
        )

        if not isinstance(self.config, dict):
            logger.warning(f"[主动消息V2] config不是字典，是 {type(self.config)}，重置为默认配置")
            self.config = DEFAULT_CONFIG_V2.copy()

        self.global_config = self.config.get("global", {})
        self.girlfriend_config = self.config.get("girlfriend", {})
        self.avatar_config = self.config.get("avatar", {})

        self._running = False
        self._timer = None
        self._timer_lock = threading.Lock()

        self.state_analyzer = None
        if self.bot and hasattr(self.bot, "lm_client"):
            self.state_analyzer = StateAnalyzer(self.bot.lm_client)

        self._conversation_states: Dict[str, dict] = {}

    def _load_config(self) -> Dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                logger.info(f"[主动消息V2] 已加载配置, 类型: {type(config)}")
                logger.debug(
                    f"[主动消息V2] config keys: {list(config.keys()) if isinstance(config, dict) else 'N/A'}"
                )
                return config
            except Exception as e:
                logger.warning(f"[主动消息V2] 加载配置失败: {e}")

        return DEFAULT_CONFIG_V2.copy()

    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[主动消息V2] 保存配置失败: {e}")

    def _get_role_config_by_role(self, role: str = "girlfriend") -> Dict:
        if role == "avatar":
            return self.avatar_config
        return self.girlfriend_config

    def _get_users(self, role: str = "girlfriend") -> List[Dict]:
        config = self._get_role_config_by_role(role)
        return config.get("users", [])

    def _save_users(self, users: List[Dict], role: str = "girlfriend"):
        config = self._get_role_config_by_role(role)
        config["users"] = users
        self._save_config()

    def add_user(
        self, wxid: str, nickname: str, role: str = "girlfriend", persona: str = "normal"
    ) -> bool:
        users = self._get_users(role)
        if any(u.get("wxid") == wxid for u in users):
            return False

        user = {
            "wxid": wxid,
            "nickname": nickname,
            "persona": persona,
            "enabled": True,
            "last_message_time": None,
            "daily_count": 0,
            "last_reset_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        }
        users.append(user)
        self._save_users(users, role)
        logger.info(f"[主动消息V2] 添加用户: {nickname} ({persona})")
        return True

    def remove_user(self, wxid: str, role: str = "girlfriend") -> bool:
        users = self._get_users(role)
        original_len = len(users)
        users = [u for u in users if u.get("wxid") != wxid]
        if len(users) < original_len:
            self._save_users(users, role)
            logger.info(f"[主动消息V2] 移除用户: {wxid}")
            return True
        return False

    def is_in_quiet_hours(self) -> bool:
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")
        quiet = self.global_config.get("quiet_hours", {})
        start = quiet.get("start", "02:00")
        end = quiet.get("end", "06:00")

        if start <= end:
            return start <= current_time < end
        else:
            return current_time >= start or current_time < end

    def _get_ai_current_state(self, persona_key: str = "normal") -> str:
        if not self.bot:
            return ""

        if hasattr(self.bot, "ai_state_system") and self.bot.ai_state_system:
            try:
                return self.bot.ai_state_system.get_state_for_prompt(persona_key)
            except Exception:
                pass

        if hasattr(self.bot, "schedule_manager") and self.bot.schedule_manager:
            try:
                return self.bot.schedule_manager.get_current_activity_for_ai(persona_key)
            except Exception:
                pass

        return ""

    def _can_proactive_chat(self, persona_key: str = "normal") -> bool:
        """判断AI当前是否可以主动发消息"""
        if not self.bot:
            return True

        if hasattr(self.bot, "schedule_manager") and self.bot.schedule_manager:
            try:
                can_chat = self.bot.schedule_manager.can_chat_now(persona_key)
                if not can_chat:
                    logger.debug(f"[主动消息V2] AI当前状态不可聊天 (persona={persona_key})")
                    return False
            except Exception as e:
                logger.debug(f"[主动消息V2] 检查聊天状态失败: {e}")

        return True

    def _get_config(self, role: str) -> Dict:
        """获取指定角色的配置"""
        return self.config.get(role, {})

    def _get_all_roles(self) -> List[str]:
        """获取所有启用的角色分组"""
        roles = []
        for role in self.config.keys():
            if role == "global":
                continue
            config = self._get_config(role)
            if config.get("enabled", False) and config.get("users"):
                roles.append(role)
        return roles

    def _get_active_users(self, role: str = "girlfriend") -> List[Dict]:
        """获取指定角色的活跃用户"""
        config = self._get_config(role)
        if not config.get("enabled", True):
            return []

        users = self._get_users(role)
        enabled_users = [u for u in users if u.get("enabled", True)]

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        for user in enabled_users:
            if user.get("last_reset_date") != today:
                user["daily_count"] = 0
                user["last_reset_date"] = today

        return enabled_users

    def _get_role_config(self, user: Dict) -> Dict:
        """获取用户所属角色的配置"""
        persona_key = user.get("persona", "normal")
        for role, config in self.config.items():
            if role == "global":
                continue
            if persona_key == role or config.get("persona", "").lower() in persona_key.lower():
                return config
        return self.girlfriend_config

    def generate_auto_message(self, user: Dict) -> str:
        now = datetime.datetime.now()
        hour = now.hour
        minute = now.minute
        current_time = f"{hour:02d}:{minute:02d}"

        persona_key = user.get("persona", "normal")
        wxid = user.get("wxid", "")
        user_name = user.get("nickname", "你")

        persona_prompt = ""
        if self.bot and hasattr(self.bot, "_get_persona_prompt"):
            try:
                session_id = f"chat_{wxid}_{persona_key}" if wxid else f"proactive_{persona_key}"
                persona_prompt = self.bot._get_persona_prompt(session_id)
            except Exception:
                pass

        ai_state = self._get_ai_current_state(persona_key)

        schedule_context = ""
        if hasattr(self.bot, "schedule_manager") and self.bot.schedule_manager:
            try:
                schedule = self.bot.schedule_manager.get_current_schedule(persona_key)
                if schedule:
                    daily_plan = schedule.get("daily_plan", {})
                    activities = daily_plan.get("activities", [])
                    if activities:
                        activity_str = "、".join(
                            [a.get("desc", "") for a in activities if a.get("desc")]
                        )
                        if activity_str:
                            schedule_context = f"今天的安排：{activity_str}\n"
            except Exception:
                pass

        time_context = self._get_time_context(now)

        memories = ""
        if self.bot and hasattr(self.bot, "enhanced_memory") and self.bot.enhanced_memory:
            try:
                wxid_for_memory = wxid if wxid else None
                if wxid_for_memory:
                    related = self.bot.enhanced_memory.get_related_memories(
                        wxid_for_memory, persona_key, top_k=3
                    )
                    if related:
                        memories = f"【相关记忆】: {related}\n"
            except Exception:
                pass

        chat_history = ""
        if self.bot and hasattr(self.bot, "session_manager"):
            try:
                session_id = f"chat_{wxid}_{persona_key}" if wxid else f"proactive_{persona_key}"
                history = self.bot.session_manager.get_messages(session_id)
                if history:
                    recent = history[-6:]
                    lines = []
                    for msg in recent:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        if content and role in ("user", "assistant"):
                            prefix = "男朋友" if role == "user" else "我"
                            lines.append(f"{prefix}: {content[:100]}")
                    if lines:
                        chat_history = "\n【最近对话】:\n" + "\n".join(lines) + "\n"
            except Exception:
                pass

        prompt = self._build_proactive_prompt(
            user_name=user_name,
            current_time=current_time,
            time_context=time_context,
            schedule_context=schedule_context,
            ai_state=ai_state,
            memories=memories,
            chat_history=chat_history,
            persona_prompt=persona_prompt,
            persona_key=persona_key,
        )

        if self.bot and hasattr(self.bot, "lm_client"):
            try:
                messages = [{"role": "user", "content": prompt}]
                message = self.bot.lm_client.chat(
                    messages,
                    temperature=0.85,
                    thinking={"type": "disabled"},
                )
                if message and len(message) > 2:
                    logger.info(f"[主动消息V2] LLM生成: {message[:50]}...")
                    return message.strip()
            except Exception as e:
                logger.warning(f"[主动消息V2] LLM生成失败: {e}")

        return self._generate_fallback_message(hour, ai_state)

    def _get_time_context(self, now: datetime.datetime) -> str:
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_names[now.weekday()]
        hour = now.hour

        if 5 <= hour < 8:
            time_desc = "清晨"
        elif 8 <= hour < 12:
            time_desc = "上午"
        elif 12 <= hour < 14:
            time_desc = "中午"
        elif 14 <= hour < 18:
            time_desc = "下午"
        elif 18 <= hour < 22:
            time_desc = "晚上"
        else:
            time_desc = "深夜"

        return f"{weekday} {hour}:{now.minute:02d}，{time_desc}"

    def _build_proactive_prompt(
        self,
        user_name: str,
        current_time: str,
        time_context: str,
        schedule_context: str,
        ai_state: str,
        memories: str,
        chat_history: str,
        persona_prompt: str,
        persona_key: str,
    ) -> str:
        time_section = f"{time_context}了\n\n" if time_context else ""

        return f"""{persona_prompt}

{schedule_context}{time_section}【你当前的状态】
{ai_state if ai_state else '刚好有空'}

{memories}{chat_history}可以自然地告诉对方你正在做什么~

主动发个消息给对方，就像女朋友突然想到男朋友想聊几句一样自然。"""

    def _generate_fallback_message(self, hour: int, ai_state: str) -> str:
        fallbacks = {
            "健身房": ["刚健完身~想你了", "在健身房呢~", "刚运动完~"],
            "吃饭": ["刚吃完饭~吃了吗~", "在吃饭呢~", "吃了吗宝~"],
            "工作": ["刚忙完~休息一下~", "在工作呢~", "忙里偷闲~"],
            "上课": ["刚下课~休息一下~", "在上课呢~"],
            "睡觉": ["刚醒来~"],
        }

        for key, msgs in fallbacks.items():
            if key in ai_state:
                return random.choice(msgs)

        if 8 <= hour < 10:
            return "早安呀~睡得好吗"
        if 22 <= hour < 24 or 0 <= hour < 2:
            return "准备休息了吗宝~"
        if 11 <= hour < 13:
            return "吃了吗~"
        if 17 <= hour < 19:
            return "吃晚饭了吗~"

        return "在干嘛呀~好久没理我了"

    def _send_proactive_message(self, user: Dict):
        """发送主动消息"""
        if not self.bot or not hasattr(self.bot, "_send_single_message"):
            logger.error("[主动消息V2] bot未初始化")
            return

        try:
            role_config = self._get_role_config(user)
            role = "girlfriend"
            for r, cfg in self.config.items():
                if r != "global" and cfg.get("persona") == role_config.get("persona"):
                    role = r
                    break

            chat_name = user.get("nickname", user.get("wxid"))
            persona_key = user.get("persona", "normal")

            logger.info(f"[主动消息V2][{role}] 发送给 {chat_name}: 生成消息中...")

            message = self.generate_auto_message(user)

            old_persona = self.bot._user_persona.get(user.get("wxid"), "normal")
            if old_persona != persona_key:
                self.bot._switch_persona(persona_key, user.get("wxid"))

            self.bot._send_single_message(chat_name=chat_name, content=message, switch_chat=True)

            if old_persona != persona_key:
                self.bot._switch_persona(old_persona, user.get("wxid"))

            user["last_message_time"] = datetime.datetime.now().isoformat()
            user["daily_count"] = user.get("daily_count", 0) + 1
            self._save_users(self._get_users(role), role)

            conv_key = f"{user.get('wxid')}_{persona_key}"
            self._conversation_states[conv_key] = {
                "last_activity": datetime.datetime.now(),
                "message_count": 0,
                "waiting_reply": True,
            }

            logger.info(f"[主动消息V2][{role}] 发送成功: {chat_name} - {message}")

        except Exception as e:
            logger.error(f"[主动消息V2] 发送失败: {e}")

    def handle_user_reply(self, wxid: str, user_nickname: str, message: str):
        """处理用户回复 - 理解语义，决定如何回应"""
        if not self.global_config.get("auto_reply_enabled", True):
            return

        users = self._get_users("girlfriend")
        user = next((u for u in users if u.get("wxid") == wxid), None)
        if not user:
            return

        persona_key = user.get("persona", "normal")
        conv_key = f"{wxid}_{persona_key}"

        conv_state = self._conversation_states.get(conv_key, {})
        conv_state["waiting_reply"] = False
        conv_state["message_count"] = conv_state.get("message_count", 0) + 1
        conv_state["last_activity"] = datetime.datetime.now()
        self._conversation_states[conv_key] = conv_state

        # 只使用关键词判断，不调用 LLM（避免污染主对话）
        self._simple_auto_reply(user, message)

    def _simple_auto_reply(self, user: Dict, message: str):
        """简单的自动回复（无LLM时）"""
        message_lower = message.lower()

        end_keywords = ["忙", "开会", "上课", "没空", "不方便"]
        if any(kw in message_lower for kw in end_keywords):
            logger.info("[主动消息V2] 用户表示忙，不回复")
            return

        continue_keywords = ["哈哈", "想", "爱你", "好呀"]
        if any(kw in message_lower for kw in continue_keywords):
            try:
                self.bot._send_single_message(
                    chat_name=user.get("nickname", user.get("wxid")),
                    content="嗯嗯~",
                    switch_chat=True,
                )
            except Exception:
                pass

    def _cleanup_stale_conversations(self):
        """清理超时的对话"""
        now = datetime.datetime.now()
        timeout_minutes = 10

        stale_keys = []
        for key, state in self._conversation_states.items():
            last_activity = state.get("last_activity")
            if last_activity and (now - last_activity).total_seconds() > timeout_minutes * 60:
                stale_keys.append(key)

        for key in stale_keys:
            del self._conversation_states[key]
            logger.info(f"[主动消息V2] 清理超时对话: {key}")

    def start_background_checker(self, check_interval: int = None):
        if self._running:
            return

        if check_interval is None:
            check_interval = self.global_config.get("check_interval_seconds", 1800)

        self._running = True

        def checker():
            while self._running:
                try:
                    self._cleanup_stale_conversations()

                    if self.is_in_quiet_hours():
                        time.sleep(check_interval)
                        continue

                    all_roles = self._get_all_roles()
                    if not all_roles:
                        time.sleep(check_interval)
                        continue

                    now = datetime.datetime.now()
                    silence_threshold = 2 * 60

                    for role in all_roles:
                        role_config = self._get_config(role)
                        if not role_config.get("enabled", True):
                            continue

                        users = self._get_users(role)
                        if not users:
                            continue

                        persona_key = users[0].get("persona", "normal")

                        can_chat = self._can_proactive_chat(persona_key)
                        if not can_chat:
                            logger.debug(f"[主动消息V2][{role}] 当前状态不可聊天，跳过")
                            continue

                        target_user = None
                        for user in users:
                            p_key = user.get("persona", "normal")
                            conv_key = f"{user.get('wxid')}_{p_key}"
                            conv_state = self._conversation_states.get(conv_key, {})

                            if conv_state.get("waiting_reply"):
                                continue

                            last_activity = conv_state.get("last_activity")
                            if last_activity:
                                if isinstance(last_activity, str):
                                    last_activity = datetime.datetime.fromisoformat(last_activity)
                                minutes_since = (now - last_activity).total_seconds() / 60
                                if minutes_since >= silence_threshold:
                                    target_user = user
                                    logger.debug(
                                        f"[主动消息V2] {user.get('nickname')} 已沉默 {int(minutes_since)} 分钟"
                                    )
                                    break
                            else:
                                last_msg = user.get("last_message_time", "")
                                if last_msg:
                                    try:
                                        if isinstance(last_msg, str):
                                            last_msg_time = datetime.datetime.fromisoformat(
                                                last_msg
                                            )
                                        else:
                                            last_msg_time = last_msg
                                        minutes_since = (now - last_msg_time).total_seconds() / 60
                                        if minutes_since >= silence_threshold:
                                            target_user = user
                                            logger.debug(
                                                f"[主动消息V2] {user.get('nickname')} 已沉默 {int(minutes_since)} 分钟"
                                            )
                                            break
                                    except Exception:
                                        target_user = user
                                        break
                                else:
                                    target_user = user
                                    break

                        if not target_user:
                            logger.debug(f"[主动消息V2][{role}] 所有用户都在2小时内对话过，跳过")
                            continue

                        logger.info(f"[主动消息V2][{role}] 定时发送: {target_user.get('nickname')}")
                        self._send_proactive_message(target_user)
                        break

                    time.sleep(check_interval)

                except Exception as e:
                    logger.error(f"[主动消息V2] 检查线程异常: {e}")
                    time.sleep(60)

        self._timer = threading.Thread(target=checker, daemon=True)
        self._timer.start()
        logger.info(f"[主动消息V2] 后台检查线程已启动 (间隔{check_interval}秒)")

    def stop_background_checker(self):
        self._running = False
        if self._timer:
            self._timer.join(timeout=5)
        logger.info("[主动消息V2] 后台检查线程已停止")

    def get_status(self) -> Dict:
        return {
            "enabled": self.girlfriend_config.get("enabled", True),
            "quiet_hours": self.is_in_quiet_hours(),
            "users_count": len(self._get_users("girlfriend")),
            "active_conversations": len(self._conversation_states),
            "auto_reply": self.global_config.get("auto_reply_enabled", True),
        }

    def list_users(self, role: str = "girlfriend") -> str:
        users = self._get_users(role)
        if not users:
            return f"暂无{role}角色用户"

        role_name = "女友" if role == "girlfriend" else "替身"
        lines = [f"{role_name}角色用户列表："]
        for user in users:
            status = "✓" if user.get("enabled") else "✗"
            lines.append(
                f"{status} {user.get('nickname')} ({user.get('persona', 'normal')}) - 今日{user.get('daily_count', 0)}条"
            )
        return "\n".join(lines)

    @property
    def enabled(self) -> bool:
        return self.girlfriend_config.get("enabled", True)

    @enabled.setter
    def enabled(self, value: bool):
        self.girlfriend_config["enabled"] = value
        self._save_config()

    @property
    def users(self) -> List[Dict]:
        return self._get_users("girlfriend")
