import json
import os
import re
import threading
import queue
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from utils.data_types import Session


class AsyncSessionManager:
    def __init__(
        self,
        data_dir: str = "data/sessions",
        memory_dir: str = "data/memory",
        write_interval: float = 2.0,
        write_batch: int = 10,
    ):
        self.data_dir = data_dir
        self.memory_dir = memory_dir
        self.write_interval = write_interval
        self.write_batch = write_batch
        self._ensure_dir()

        self._pending_session_writes: Dict[str, float] = {}
        self._pending_memory_writes: Dict[str, float] = {}
        self._pending_session_data: Dict[str, Any] = {}
        self._pending_memory_data: Dict[str, Any] = {}
        self._write_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._flush_lock = threading.Lock()
        self._worker = threading.Thread(target=self._write_worker, daemon=True)
        self._worker.start()

    def _ensure_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        if not os.path.exists(self.memory_dir):
            os.makedirs(self.memory_dir)

    def _safe_name(self, session_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-.]+", "_", session_id)

    def _memory_path(self, session_id: str) -> str:
        return os.path.join(self.memory_dir, f"{self._safe_name(session_id)}.json")

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.data_dir, f"{session_id}.json")

    def _queue_write(self, write_type: str, session_id: str):
        self._write_queue.put((write_type, session_id, time.time()))

    def _write_worker(self):
        last_flush_time = time.time()
        while not self._stop_event.is_set():
            try:
                item = self._write_queue.get(timeout=0.5)
                if item is None:
                    continue
                write_type, session_id, enqueue_time = item

                if write_type == "session":
                    self._pending_session_writes[session_id] = enqueue_time
                else:
                    self._pending_memory_writes[session_id] = enqueue_time

                should_flush = (
                    len(self._pending_session_writes) >= self.write_batch
                    or len(self._pending_memory_writes) >= self.write_batch
                    or time.time() - last_flush_time >= self.write_interval
                )

                if should_flush:
                    self._flush_all()
                    last_flush_time = time.time()

            except queue.Empty:
                if time.time() - last_flush_time >= self.write_interval:
                    self._flush_all()
                    last_flush_time = time.time()

    def _flush_all(self):
        with self._flush_lock:
            if self._pending_session_writes or self._pending_memory_writes:
                for session_id in list(self._pending_session_writes.keys()):
                    self._write_session_file(session_id)
                for session_id in list(self._pending_memory_writes.keys()):
                    self._write_memory_file(session_id)
                self._pending_session_writes.clear()
                self._pending_memory_writes.clear()

    def _write_session_file(self, session_id: str):
        if session_id not in self._pending_session_data:
            return
        filepath = self._session_path(session_id)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._pending_session_data[session_id], f, ensure_ascii=False, indent=2)
            del self._pending_session_data[session_id]
        except Exception:
            pass

    def _write_memory_file(self, session_id: str):
        if session_id not in self._pending_memory_data:
            return
        filepath = self._memory_path(session_id)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._pending_memory_data[session_id], f, ensure_ascii=False, indent=2)
            del self._pending_memory_data[session_id]
        except Exception:
            pass

    def save_session_async(self, session_id: str, session_data: Dict):
        self._pending_session_data[session_id] = session_data
        self._queue_write("session", session_id)

    def save_memory_async(self, session_id: str, memory_data: Dict):
        self._pending_memory_data[session_id] = memory_data
        self._queue_write("memory", session_id)

    def flush(self):
        self._flush_all()

    def stop(self):
        self._stop_event.set()
        self._flush_all()
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)


class SessionManager:
    def __init__(
        self,
        data_dir: str = "data/sessions",
        memory_dir: str = "data/memory",
        async_write_interval: float = 2.0,
        async_write_batch: int = 10,
        async_enabled: bool = True,
    ):
        self.data_dir = data_dir
        self.memory_dir = memory_dir
        self.async_write_interval = async_write_interval
        self.async_write_batch = async_write_batch
        self.async_enabled = async_enabled
        self.sessions: Dict[str, Session] = {}
        self._ensure_dir()
        self._async_mgr = None
        if self.async_enabled:
            self._async_mgr = AsyncSessionManager(
                data_dir, memory_dir, async_write_interval, async_write_batch
            )

    def _ensure_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        if not os.path.exists(self.memory_dir):
            os.makedirs(self.memory_dir)

    def _safe_name(self, session_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-.]+", "_", session_id)

    def _memory_path(self, session_id: str) -> str:
        return os.path.join(self.memory_dir, f"{self._safe_name(session_id)}.json")

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.data_dir, f"{session_id}.json")

    def get_session(self, session_id: str) -> Session:
        """获取或创建会话"""
        if session_id not in self.sessions:
            loaded = self.load_session(session_id)
            self.sessions[session_id] = loaded if loaded else Session(session_id)
        return self.sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        """添加消息"""
        session = self.get_session(session_id)
        session.add_message(role, content)

    def get_messages(self, session_id: str) -> List[Dict[str, str]]:
        """获取会话消息"""
        session = self.get_session(session_id)
        return session.get_messages()

    def save_session(self, session_id: str):
        """保存会话到文件"""
        if session_id not in self.sessions:
            return

        session = self.sessions[session_id]
        if self._async_mgr:
            self._async_mgr.save_session_async(session_id, session.to_dict())
        else:
            filepath = self._session_path(session_id)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    def load_session(self, session_id: str) -> Optional[Session]:
        """从文件加载会话"""
        filepath = self._session_path(session_id)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                session = Session.from_dict(data)
                self.sessions[session_id] = session
                return session
        return None

    def load_memory(self, session_id: str) -> Dict[str, Any]:
        filepath = self._memory_path(session_id)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "recent_context": [],
            "behavior": {
                "total_user_messages": 0,
                "question_ratio": 0.0,
                "emoji_ratio": 0.0,
                "avg_length": 0.0,
                "night_active_ratio": 0.0,
                "brief_ratio": 0.0,
            },
            "traits": [],
            "top_keywords": [],
        }

    def save_memory(self, session_id: str, memory: Dict[str, Any]):
        if self._async_mgr:
            self._async_mgr.save_memory_async(session_id, memory)
        else:
            filepath = self._memory_path(session_id)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)

    def _extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}|\d{2,}", text.lower())
        stopwords = {
            "这个",
            "那个",
            "你们",
            "我们",
            "然后",
            "因为",
            "所以",
            "就是",
            "一下",
            "可以",
            "还有",
            "已经",
            "一个",
            "不是",
            "什么",
            "怎么",
            "还是",
            "真的",
            "那个",
            "今天",
            "明天",
            "现在",
            "请问",
            "需要",
        }
        return [w for w in words if w not in stopwords][:20]

    def _build_traits(self, stats: Dict[str, float], top_keywords: List[str]) -> List[str]:
        traits = []
        if stats.get("brief_ratio", 0) >= 0.6:
            traits.append("偏好短句交流")
        if stats.get("question_ratio", 0) >= 0.35:
            traits.append("提问频率较高")
        if stats.get("emoji_ratio", 0) >= 0.2:
            traits.append("经常使用表情")
        if stats.get("night_active_ratio", 0) >= 0.3:
            traits.append("夜间活跃")
        if top_keywords:
            traits.append(f"常谈主题: {', '.join(top_keywords[:3])}")
        return traits[:6]

    def update_memory(self, session_id: str, user_text: str, assistant_text: str = ""):
        memory = self.load_memory(session_id)
        behavior = memory.get("behavior", {})
        total = int(behavior.get("total_user_messages", 0)) + 1
        prev_total = max(1, total - 1)

        text = (user_text or "").strip()
        length = len(text)
        is_question = 1 if ("?" in text or "？" in text) else 0
        emoji_count = len(re.findall(r"\[[^\]]+\]|[\U0001F300-\U0001FAFF]", text))
        has_emoji = 1 if emoji_count > 0 else 0
        is_brief = 1 if length <= 12 else 0
        hour = datetime.now().hour
        is_night = 1 if hour >= 22 or hour <= 6 else 0

        def running_avg(old_avg: float, val: float) -> float:
            return ((old_avg * prev_total) + val) / total

        behavior["total_user_messages"] = total
        behavior["avg_length"] = round(
            running_avg(float(behavior.get("avg_length", 0.0)), float(length)), 2
        )
        behavior["question_ratio"] = round(
            running_avg(float(behavior.get("question_ratio", 0.0)), float(is_question)), 3
        )
        behavior["emoji_ratio"] = round(
            running_avg(float(behavior.get("emoji_ratio", 0.0)), float(has_emoji)), 3
        )
        behavior["brief_ratio"] = round(
            running_avg(float(behavior.get("brief_ratio", 0.0)), float(is_brief)), 3
        )
        behavior["night_active_ratio"] = round(
            running_avg(float(behavior.get("night_active_ratio", 0.0)), float(is_night)), 3
        )

        keyword_counter = memory.get("keyword_counter", {})
        for kw in self._extract_keywords(text):
            keyword_counter[kw] = int(keyword_counter.get(kw, 0)) + 1
        sorted_kw = sorted(keyword_counter.items(), key=lambda x: x[1], reverse=True)
        top_keywords = [k for k, _ in sorted_kw[:12]]

        recent = memory.get("recent_context", [])
        recent.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "user": text[:300],
                "assistant": (assistant_text or "").strip()[:300],
            }
        )
        recent = recent[-20:]

        memory["updated_at"] = datetime.now().isoformat()
        memory["recent_context"] = recent
        memory["behavior"] = behavior
        memory["keyword_counter"] = keyword_counter
        memory["top_keywords"] = top_keywords
        memory["traits"] = self._build_traits(behavior, top_keywords)
        self.save_memory(session_id, memory)

    def get_memory_prompt(self, session_id: str) -> str:
        memory = self.load_memory(session_id)
        traits = memory.get("traits", [])
        top_keywords = memory.get("top_keywords", [])
        recent = memory.get("recent_context", [])[-4:]
        lines = [
            f"会话ID: {session_id}",
            f"用户特征: {'；'.join(traits) if traits else '暂无'}",
            f"关键词: {', '.join(top_keywords[:8]) if top_keywords else '暂无'}",
            "近期用户表达:",
        ]
        if recent:
            for item in recent:
                user_text = item.get("user", "")
                lines.append(f"- 用户: {user_text}")
        else:
            lines.append("- 暂无")
        return "\n".join(lines)

    def clear_session(self, session_id: str):
        """清除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]

        filepath = self._session_path(session_id)
        if os.path.exists(filepath):
            os.remove(filepath)
        memory_path = self._memory_path(session_id)
        if os.path.exists(memory_path):
            os.remove(memory_path)

    def flush(self):
        """刷新所有待写入的数据"""
        if self._async_mgr:
            self._async_mgr.flush()

    def stop(self):
        """停止异步写入线程"""
        if self._async_mgr:
            self._async_mgr.stop()
