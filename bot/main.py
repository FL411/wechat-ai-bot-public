"""
微信 AI 机器人 - 模块化重构版本
"""

# ruff: noqa: E402

import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import warnings

warnings.filterwarnings("ignore", message=".*AOTriton backend.*")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

from bot.comtypes_cache import configure_comtypes_cache

configure_comtypes_cache()

import requests
import time
import queue
import threading
import re
import json
import asyncio
import websockets
import base64
import io
import uiautomation as auto
from loguru import logger


def _configure_bot_file_logging() -> None:
    log_dir = os.path.join(BOT_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "bot_current.log")
    if getattr(_configure_bot_file_logging, "configured", False):
        return
    logger.add(
        log_path,
        level=os.environ.get("BOT_LOG_LEVEL", "DEBUG"),
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
    )
    _configure_bot_file_logging.configured = True


_configure_bot_file_logging()
from typing import Optional, Dict, List
from PIL import Image

from bot.config import load_bot_config, _get_config_value
from bot.window import WindowController
from bot.sender import MessageSender
from bot.search import SearchDecisionCache
from bot.prompt import PromptBuilder, PromptContext, PersonaLoader
from bot.wechat_adapter import WeChatMessageAdapter

from clients.factory import create_client
from memory.session_manager import SessionManager
from memory.enhanced_memory import EnhancedMemoryManager
from schedule.schedule_manager import ScheduleManager
from schedule.ai_state import AIStateSystem
from proactive.manager import ProactiveUserManagerV2
from bot.emoji_manager import EmojiManager
from utils.utils import build_msg_id

_uia_init_main = auto.UIAutomationInitializerInThread()


def _ensure_uia_init():
    """确保当前线程已初始化 UIAutomation"""
    t = threading.current_thread()
    if not hasattr(t, "_uia_init"):
        t._uia_init = auto.UIAutomationInitializerInThread()


def _url_to_base64_image(image_url: str, timeout: int = 10) -> str:
    """将图片 URL 转为 base64 编码"""
    try:
        response = requests.get(image_url, timeout=timeout)
        response.raise_for_status()
        image_data = response.content
        img = Image.open(io.BytesIO(image_data))
        img_format = img.format.lower() if img.format else "jpeg"
        if img_format == "jpg":
            img_format = "jpeg"
        b64_data = base64.b64encode(image_data).decode("utf-8")
        return f"data:image/{img_format};base64,{b64_data}"
    except Exception as e:
        logger.warning(f"[图片] 下载或转换图片失败: {e}")
        return None


def _timeout_call(func, default=None, timeout_ms=3000):
    """带超时的Windows API调用，防止阻塞"""
    result = None
    finished = threading.Event()

    def wrapper():
        nonlocal result
        try:
            result = func()
        except Exception:
            result = default
        finally:
            finished.set()

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    t.join(timeout=timeout_ms / 1000)
    return default if t.is_alive() else (result if result is not None else default)


_search_cache = SearchDecisionCache(ttl_seconds=300)


def _is_debug_enabled() -> bool:
    return os.environ.get("WECHAT_BOT_DEBUG", "0") == "1"


class WeChatAIBot:
    """微信 AI 机器人 - 模块化版本"""

    def __init__(self, ignore_group_chat: bool = None, lmstudio_url: str = None, model: str = None):
        cfg = load_bot_config()

        self.ignore_group_chat = (
            ignore_group_chat
            if ignore_group_chat is not None
            else _get_config_value(cfg, "wechat", "ignore_group_chat", default=True)
        )
        self.webui_url = _get_config_value(
            cfg, "wechat", "webui_url", default="http://localhost:5678"
        )
        self.ws_url = _get_config_value(cfg, "wechat", "ws_url", default="ws://localhost:5679")
        self.last_timestamp = 0
        self._message_stream_since = int(time.time())
        self.replied_messages = set()
        self.seen_messages = set()
        self.message_adapter = WeChatMessageAdapter(
            enabled=_get_config_value(
                cfg, "wechat", "outgoing_echo_filter", "enabled", default=True
            ),
            echo_window_seconds=_get_config_value(
                cfg, "wechat", "outgoing_echo_filter", "window_seconds", default=120
            ),
            similarity_threshold=_get_config_value(
                cfg, "wechat", "outgoing_echo_filter", "similarity_threshold", default=0.96
            ),
            cross_session_window_seconds=_get_config_value(
                cfg, "wechat", "outgoing_echo_filter", "cross_session_window_seconds", default=20
            ),
        )

        llm_config = dict(_get_config_value(cfg, "llm", default={}) or {})
        if lmstudio_url:
            llm_config["base_url"] = lmstudio_url
        if model is not None:
            llm_config["model"] = model

        if llm_config.get("backend") == "lmstudio":
            raise ValueError(
                "lmstudio 后端已移除。请改用统一 llm 配置："
                "base_url: http://localhost:1234/v1，model: 手动填写模型名，"
                "生成参数放入 llm.params。"
            )

        self.lm_client = create_client(llm_config)
        self._use_messages_format = True

        self._llm_backend = "openai_compatible"
        logger.info("LLM 后端: OpenAI-Compatible")

        self.async_write_enabled = _get_config_value(
            cfg, "bot", "async_write_enabled", default=True
        )
        self.async_write_interval = _get_config_value(
            cfg, "bot", "async_write_interval", default=2.0
        )
        self.async_write_batch = _get_config_value(cfg, "bot", "async_write_batch", default=10)

        self.session_manager = SessionManager(
            async_write_interval=self.async_write_interval,
            async_write_batch=self.async_write_batch,
            async_enabled=self.async_write_enabled,
        )

        self.enhanced_memory = EnhancedMemoryManager(
            llm_client=self.lm_client,
            summary_interval=_get_config_value(cfg, "bot", "summary_interval", default=15),
            max_semantic_items=_get_config_value(cfg, "bot", "max_semantic_items", default=500),
            use_bge=_get_config_value(cfg, "bot", "use_bge", default=True),
            use_bm25=_get_config_value(cfg, "bot", "use_bm25", default=True),
            use_compression=_get_config_value(cfg, "bot", "use_compression", default=True),
        )

        self.model = llm_config.get("model", "")

        persona_dir = _get_config_value(cfg, "persona", "persona_dir", default="data/personas")
        if not os.path.isabs(persona_dir):
            persona_dir = os.path.join(BOT_DIR, persona_dir)
        active_persona = _get_config_value(cfg, "persona", "active", default=None)
        self.persona_loader = PersonaLoader(persona_dir)
        self.prompt_builder = PromptBuilder(cfg, self.persona_loader)
        self.active_persona = self.persona_loader.choose_default(active_persona)
        self._personas = self.persona_loader.as_legacy_personas()

        self._user_persona: Dict[str, str] = {}
        default_profile = self.persona_loader.load(self.active_persona)
        persona_prefs = {
            "key": default_profile.key,
            "name": default_profile.name or "小明",
            "description": default_profile.identity
            or default_profile.setting[:120]
            or "普通年轻人",
            "schedule_preferences": {},
        }
        self.current_persona_name = persona_prefs.get("name", "小明")
        self.schedule_manager = ScheduleManager(
            lm_client=self.lm_client, persona_prefs=persona_prefs
        )
        self.ai_state_system = AIStateSystem(schedule_manager=self.schedule_manager)

        if _get_config_value(cfg, "bot", "auto_schedule", default=True):
            self._schedule_generation_done = False
            self._schedule_for_memory = None

            def _generate_schedules():
                for key, persona_config in self._personas.items():
                    if key == self.active_persona:
                        continue
                    try:
                        prefs = persona_config.copy()
                        prefs["key"] = key
                        self.schedule_manager.ensure_today_schedule(prefs, key)
                    except Exception as e:
                        logger.warning(f"人设 '{key}' 日程生成失败: {e}")

            def async_generate_schedule():
                schedule = self.schedule_manager.ensure_today_schedule(
                    persona_prefs, self.active_persona
                )
                self.current_schedule = schedule
                self._schedule_for_memory = self.schedule_manager.format_schedule_for_memory(
                    schedule
                )
                self._schedule_generation_done = True
                _generate_schedules()

            self.current_schedule = None
            t = threading.Thread(target=async_generate_schedule, daemon=True)
            t.start()
            logger.info("日程正在后台生成中...")
        else:
            self.current_schedule = None
            self._schedule_for_memory = None

        llm_params = llm_config.get("params", {}) or {}
        self.reply_temperature = llm_params.get("temperature")
        self.reply_top_p = llm_params.get("top_p")
        self.reply_repeat_penalty = llm_params.get("repeat_penalty")
        self.reply_repeat_last_n = llm_params.get("repeat_last_n")

        self.search_enabled = _get_config_value(cfg, "search", "enabled", default=True)
        self.search_max_results = _get_config_value(cfg, "search", "max_results", default=5)
        self.search_priority = _get_config_value(cfg, "search", "priority", default=["mcp"])
        self.tavily_api_key = (
            _get_config_value(cfg, "search", "tavily", "api_key", default="") or ""
        )
        self.tavily_max_results = _get_config_value(
            cfg, "search", "tavily", "max_results", default=5
        )

        self.reply_delay = _get_config_value(cfg, "bot", "reply_delay", default=0)
        self.max_memory_chars = _get_config_value(cfg, "bot", "max_memory_chars", default=1200)
        self.max_total_chars = _get_config_value(cfg, "bot", "max_total_chars", default=4500)
        self.max_history_per_session = _get_config_value(
            cfg, "bot", "max_history_per_session", default=20
        )

        self.current_chat = ""
        self._chat_name_cache = {}
        self._msg_buffer: Dict[str, Dict] = {}
        self._msg_buffer_timer: Dict[str, threading.Timer] = {}
        self._buffer_lock = threading.Lock()
        self.reply_queue = queue.Queue()
        self.stop_event = threading.Event()

        self.wx_window: Optional[auto.WindowControl] = None
        self.window_controller = WindowController(wx_window=None)

        try:
            from bot.reminder_manager import ReminderManager

            self.reminder_manager = ReminderManager(self)
            logger.info("定时提醒管理器已初始化")
        except Exception as e:
            self.reminder_manager = None
            logger.warning(f"提醒模块初始化失败: {e}")

        # 来电回拨功能已移除
        # try:
        #     from call_answer_monitor import CallAnswerMonitor
        #     self.call_monitor = CallAnswerMonitor(...)
        # except Exception as e:
        #     self.call_monitor = None
        self.call_monitor = None

        try:
            self.emoji_manager = EmojiManager()
            logger.info("表情包管理器已初始化")
        except Exception as e:
            self.emoji_manager = None
            logger.warning(f"表情包管理器初始化失败: {e}")

        try:
            self.proactive_manager = ProactiveUserManagerV2(bot=self)
            status = self.proactive_manager.get_status()
            logger.info(f"主动消息管理器V2已初始化 (用户:{status.get('users_count', 0)}人)")
        except Exception as e:
            self.proactive_manager = None
            logger.warning(f"主动消息管理器初始化失败: {e}")

    def connect_wechat_window(self):
        """连接微信窗口"""
        if self.window_controller.connect_wechat():
            self.wx_window = self.window_controller.wx_window
            return True
        return False

    def _ensure_wechat_foreground(self) -> bool:
        """激活微信窗口"""
        if not self.window_controller.wx_window:
            logger.warning("_ensure_wechat_foreground: wx_window未初始化")
            return False
        return self.window_controller._ensure_wechat_foreground()

    def switch_chat(self, chat_name: str) -> bool:
        """切换聊天"""
        return self.window_controller.switch_chat(chat_name)

    def _convert_messages_to_text(self, messages: list) -> str:
        """将 messages 列表转换为单文本格式。"""
        system_parts = []
        user_messages = []
        assistant_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)
            else:
                content = str(content) if content else ""

            if role == "system":
                system_parts.append(content)
            elif role == "user":
                user_messages.append(content)
            elif role == "assistant":
                assistant_messages.append(content)

        history_lines = []
        for i, msg in enumerate(assistant_messages):
            if i < len(user_messages) and user_messages[i]:
                history_lines.append(f"user: {user_messages[i]}")
            if msg:
                history_lines.append(f"assistant: {msg}")

        parts = []
        if system_parts:
            parts.append(system_parts[0])
        if history_lines:
            parts.append("\n".join(history_lines[-8:]))
        if user_messages:
            parts.append(f"user: {user_messages[-1]}")

        return "\n\n".join(parts)

    def _call_llm_chat(self, messages: list, **kwargs):
        """统一调用 LLM"""
        if self._use_messages_format:
            return self.lm_client.chat(messages, **kwargs)
        else:
            text = self._convert_messages_to_text(messages)
            timeout = kwargs.pop("timeout", 90)
            return self.lm_client.chat(text, timeout=timeout)

    def _send_reply(self, text: str, session_name: str, delay_per_char: float = 0.05) -> bool:
        """发送回复"""
        sender = MessageSender(self.window_controller)
        self.message_adapter.record_sent(session_name, text)
        for part in sender._split_message(text):
            self.message_adapter.record_sent(session_name, part)
        ok = sender.send_message(text, session_name)
        logger.info(f"[发送回复] {session_name}: {'成功' if ok else '失败'}")
        return ok

    def run(self):
        """运行机器人"""
        if not self.connect_wechat_window():
            return

        ws_url = self.ws_url
        logger.info(f"连接消息流: {ws_url}")

        time.sleep(2)
        self._ensure_wechat_foreground()

        recv_thread = threading.Thread(target=self._recv_loop, args=(ws_url,), daemon=True)
        recv_thread.start()

        proc_thread = threading.Thread(target=self._reply_processor, daemon=True)
        proc_thread.start()

        try:
            while not self.stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            self.stop_event.set()
            logger.info("机器人已停止")

    def _recv_loop(self, ws_url: str):
        """接收消息循环"""
        if ws_url.startswith(("ws://", "wss://")):
            self._recv_websocket_loop(ws_url, fallback_url=self._message_stream_url())
        else:
            self._recv_sse_loop(ws_url)

    def _message_stream_url(self) -> str:
        return f"{self.webui_url.rstrip('/')}/stream"

    def _recv_websocket_loop(self, ws_url: str, fallback_url: str = None):
        """接收 WebSocket 消息，失败时可切换到 SSE。"""

        async def _connect():
            failure_count = 0
            while not self.stop_event.is_set():
                try:
                    async with websockets.connect(ws_url, ping_interval=30) as ws:
                        failure_count = 0
                        logger.info("WebSocket 已连接")
                        async for msg_text in ws:
                            try:
                                msg = json.loads(msg_text)
                                self._handle_message(msg)
                            except json.JSONDecodeError:
                                logger.warning(f"消息解析失败: {msg_text[:100]}")
                except Exception as e:
                    failure_count += 1
                    logger.error(f"WebSocket 连接错误: {e}")
                    if fallback_url and failure_count >= 1:
                        logger.warning(f"WebSocket 不可用，切换到 SSE: {fallback_url}")
                        return "fallback"
                    time.sleep(5)

        result = asyncio.run(_connect())
        if result == "fallback" and not self.stop_event.is_set():
            self._recv_sse_loop(fallback_url)

    def _recv_sse_loop(self, stream_url: str):
        """接收监听器 SSE 消息。"""
        while not self.stop_event.is_set():
            try:
                logger.info(f"连接 SSE: {stream_url}")
                with requests.get(stream_url, stream=True, timeout=(5, 60)) as response:
                    response.raise_for_status()
                    response.encoding = "utf-8"
                    logger.info("SSE 已连接")
                    self._load_recent_history(stream_url)
                    event_name = ""
                    data_lines = []
                    for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
                        if self.stop_event.is_set():
                            break
                        if raw_line is None:
                            continue
                        line = raw_line.rstrip("\r")
                        if line == "":
                            if data_lines:
                                self._handle_sse_event(event_name, "\n".join(data_lines))
                            event_name = ""
                            data_lines = []
                            continue
                        if line.startswith(":"):
                            continue
                        if line.startswith("event:"):
                            event_name = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
            except requests.RequestException as e:
                logger.error(f"SSE 连接错误: {e}")
                time.sleep(5)
            except Exception as e:
                logger.error(f"SSE 处理错误: {e}")
                time.sleep(5)

    def _load_recent_history(self, stream_url: str):
        """SSE 重连后补拉启动后的消息，避免短暂断线漏消息。"""
        history_url = (
            stream_url.rsplit("/", 1)[0]
            + f"/api/history?since={self._message_stream_since}&limit=100"
        )
        try:
            response = requests.get(history_url, timeout=5)
            response.raise_for_status()
            response.encoding = "utf-8"
            messages = response.json()
            for msg in messages:
                self._handle_message(msg)
                self._message_stream_since = max(
                    self._message_stream_since, int(msg.get("timestamp", 0))
                )
        except Exception as e:
            logger.warning(f"补拉历史消息失败: {e}")

    def _handle_sse_event(self, event_name: str, data_text: str):
        if event_name:
            return
        try:
            msg = json.loads(data_text)
        except json.JSONDecodeError:
            logger.warning(f"SSE 消息解析失败: {data_text[:100]}")
            return
        if msg.get("event") or "username" not in msg or "timestamp" not in msg:
            return
        self._message_stream_since = max(self._message_stream_since, int(msg.get("timestamp", 0)))
        self._handle_message(msg)

    def _handle_message(self, msg: dict):
        """处理接收到的消息"""
        msg = self.message_adapter.normalize(msg)
        msg_id = build_msg_id(msg)

        if msg_id in self.seen_messages:
            return
        self.seen_messages.add(msg_id)
        if len(self.seen_messages) > 50000:
            self.seen_messages.clear()

        if self.message_adapter.should_ignore(msg):
            logger.info(f"[消息过滤] 忽略自己发出的消息回声: {msg.get('content', '')[:30]}")
            return

        is_group = msg.get("isGroup", msg.get("is_group", False))
        if self.ignore_group_chat and is_group:
            return

        content = msg.get("content", "").strip()
        if not content:
            return
        username = msg.get("username", "")
        msg_timestamp = msg.get("timestamp", 0)

        with self._buffer_lock:
            if username not in self._msg_buffer:
                self._msg_buffer[username] = {
                    "msg": msg,
                    "content": content,
                    "timestamp": msg_timestamp,
                    "count": 1,
                }
                self._start_buffer_timer(username)
            else:
                buf = self._msg_buffer[username]
                time_diff = msg_timestamp - buf["timestamp"]
                if time_diff <= 3:
                    buf["content"] += "\n" + content
                    buf["timestamp"] = msg_timestamp
                    buf["count"] += 1
                    if self._msg_buffer_timer.get(username):
                        self._msg_buffer_timer[username].cancel()
                    self._start_buffer_timer(username)
                else:
                    self._flush_buffer(username)
                    self._msg_buffer[username] = {
                        "msg": msg,
                        "content": content,
                        "timestamp": msg_timestamp,
                        "count": 1,
                    }
                    self._start_buffer_timer(username)

    def _start_buffer_timer(self, username: str):
        """启动缓冲计时器"""
        timer = threading.Timer(5.0, self._flush_buffer, args=(username,))
        self._msg_buffer_timer[username] = timer
        timer.start()

    def _flush_buffer(self, username: str):
        """将缓冲的消息推入处理队列"""
        with self._buffer_lock:
            if username not in self._msg_buffer:
                return
            buf = self._msg_buffer.pop(username)
            if username in self._msg_buffer_timer:
                self._msg_buffer_timer.pop(username)

        msg = buf["msg"].copy()
        content = buf["content"]
        count = buf["count"]
        sender = msg.get("chat", "") or username
        is_group = msg.get("isGroup", msg.get("is_group", False))

        if count > 1:
            logger.info(f"[收到消息] {sender}: (合并{count}条) {content[:50]}...")
        else:
            display_content = content[:50] + "..." if len(content) > 50 else content
            logger.info(f"[收到消息] {sender}: {display_content}")

        self.reply_queue.put(
            {
                "msg_id": build_msg_id(msg),
                "content": content,
                "sender": sender,
                "username": username,
                "room": msg.get("room", ""),
                "session_name": sender,
                "timestamp": buf["timestamp"],
                "_merged_count": count,
                "is_group": is_group,
            }
        )

    def _reply_processor(self):
        """回复处理线程"""
        _ensure_uia_init()
        while not self.stop_event.is_set():
            try:
                item = self.reply_queue.get(timeout=1)
                self._process_reply(item)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"处理回复时出错: {e}")

    def _process_reply(self, item: dict):
        """处理单条回复"""
        content = item["content"]
        session_name = item["session_name"]

        if content.startswith("/"):
            self._handle_command(content, session_name, item)
            return

        self._generate_and_send_reply(content, session_name)

    def _handle_command(self, cmd: str, session_name: str, item: dict):
        """处理命令"""
        cmd = cmd.strip()
        logger.info(f"[命令] {session_name}: {cmd}")

        if cmd == "/new":
            self.session_manager.clear_session(session_name)
            self._send_reply("好的，开始新对话！", session_name)
        elif cmd.startswith("/new"):
            msg = cmd[4:].strip()
            self.session_manager.clear_session(session_name)
            self._send_reply("好的，开始新对话！", session_name)
            if msg:
                self._generate_and_send_reply(msg, session_name)
        elif cmd in ("/正常", "/s", "/S"):
            self._switch_persona("normal", session_name)
        elif cmd.startswith("/mm") or cmd.startswith("/MM"):
            self._switch_persona("mm", session_name)
        elif cmd.startswith("/"):
            logger.debug(f"忽略未知命令: {cmd}")

    def _switch_persona(self, persona_key: str, session_name: str):
        """切换人设"""
        if persona_key == "normal":
            persona_key = self.active_persona
        if persona_key not in self._personas:
            logger.warning(f"人设不存在，保持当前人设: {persona_key}")
            return
        if persona_key == self._user_persona.get(session_name, self.active_persona):
            return

        self._user_persona[session_name] = persona_key
        persona = self._personas.get(persona_key, {})
        name = persona.get("name", "角色")
        logger.info(f"切换到人设: {persona_key} ({name})")
        self._send_reply(f"好的，我现在是{name}了！", session_name)

    def _generate_and_send_reply(self, user_message: str, session_name: str):
        """生成并发送回复"""
        try:
            messages = self._build_messages(user_message, session_name)
            reply = self._call_llm_chat(
                messages,
                model=self.model,
                temperature=self.reply_temperature,
                top_p=self.reply_top_p,
                repeat_penalty=self.reply_repeat_penalty,
                repeat_last_n=self.reply_repeat_last_n,
            )

            reply = self._clean_reply_text(reply)

            if reply:
                logger.info(f"[生成回复] {session_name}: {len(reply)} 字")
                self._send_reply(reply, session_name)
                self.session_manager.add_message(session_name, "user", user_message)
                self.session_manager.add_message(session_name, "assistant", reply)
            else:
                logger.warning(f"[生成回复] {session_name}: 空回复")
        except Exception as e:
            logger.error(f"生成回复失败: {e}")

    def _build_messages(self, user_message: str, session_name: str) -> List[Dict]:
        """构建消息列表"""
        persona_key = self._user_persona.get(session_name, self.active_persona)
        history = self.session_manager.get_messages(session_name)
        result = self.prompt_builder.build_chat_messages(
            PromptContext(
                user_message=user_message,
                session_name=session_name,
                persona=persona_key,
                schedule_context=self._schedule_for_memory or "",
                history=history,
            )
        )
        self._last_prompt_stats = result.stats
        return result.messages

    def _clean_reply_text(self, text: str) -> str:
        """清洗回复文本"""
        if not text:
            return ""
        text = text.strip()
        text = re.sub(r"<\/?think>[\s\S]*?<\/?think>", "", text)
        text = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", text)
        return text.strip()


def main():
    """主入口"""
    logger.info("=" * 50)
    logger.info("微信 AI 机器人 (模块化版本) 启动中...")
    logger.info("=" * 50)

    bot = WeChatAIBot()
    bot.run()


if __name__ == "__main__":
    main()
