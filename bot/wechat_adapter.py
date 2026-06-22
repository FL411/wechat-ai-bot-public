"""微信监听消息适配层。

保持外部 wechat-decrypt 项目不变，在主项目内完成消息标准化和自己消息回声过滤。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional


@dataclass
class SentMessageRecord:
    session_name: str
    content: str
    created_at: float


class WeChatMessageAdapter:
    """把 wechat-decrypt 的原始消息转换成 bot 可消费的标准消息。"""

    def __init__(
        self,
        enabled: bool = True,
        echo_window_seconds: int = 120,
        similarity_threshold: float = 0.96,
        cross_session_window_seconds: int = 20,
        max_records: int = 200,
    ):
        self.enabled = enabled
        self.echo_window_seconds = max(1, int(echo_window_seconds))
        self.similarity_threshold = float(similarity_threshold)
        self.cross_session_window_seconds = max(0, int(cross_session_window_seconds))
        self.max_records = max(10, int(max_records))
        self._sent_records: List[SentMessageRecord] = []

    def normalize(self, raw_msg: Dict[str, Any]) -> Dict[str, Any]:
        """保留原始字段，并补充标准字段。"""
        msg = dict(raw_msg or {})
        msg.setdefault("is_group", msg.get("isGroup", False))
        msg.setdefault("session_name", self.session_name(msg))
        return msg

    def record_sent(self, session_name: str, content: str) -> None:
        """记录 bot 刚发出的消息，用于过滤监听器回推。"""
        content = self._normalize_text(content)
        session_name = str(session_name or "").strip()
        if not self.enabled or not content:
            return
        self._prune(time.time())
        self._sent_records.append(SentMessageRecord(session_name, content, time.time()))
        if len(self._sent_records) > self.max_records:
            self._sent_records = self._sent_records[-self.max_records :]

    def should_ignore(self, raw_msg: Dict[str, Any]) -> bool:
        """判断是否应忽略该消息。"""
        if not raw_msg:
            return True
        direction = str(raw_msg.get("direction") or "").lower()
        if direction == "out":
            return True
        if not self.enabled:
            return False
        return self._is_sent_echo(raw_msg)

    def session_name(self, msg: Dict[str, Any]) -> str:
        return str(
            msg.get("session_name")
            or msg.get("room")
            or msg.get("chat")
            or msg.get("sender")
            or msg.get("username")
            or ""
        ).strip()

    def _is_sent_echo(self, msg: Dict[str, Any]) -> bool:
        content = self._normalize_text(msg.get("content", ""))
        if not content:
            return False
        now = time.time()
        self._prune(now)
        session_name = self.session_name(msg)
        for record in list(self._sent_records):
            same_session = (
                not session_name or not record.session_name or session_name == record.session_name
            )
            in_cross_session_window = (
                self.cross_session_window_seconds > 0
                and now - record.created_at <= self.cross_session_window_seconds
            )
            if not same_session and not in_cross_session_window:
                continue
            if self._same_text(record.content, content):
                return True
        return False

    def _prune(self, now: float) -> None:
        cutoff = now - self.echo_window_seconds
        self._sent_records = [
            record for record in self._sent_records if record.created_at >= cutoff
        ]

    def _same_text(self, sent_text: str, incoming_text: str) -> bool:
        if not sent_text or not incoming_text:
            return False
        if sent_text == incoming_text:
            return True
        shorter = min(len(sent_text), len(incoming_text))
        if shorter >= 8 and (
            sent_text.startswith(incoming_text) or incoming_text.startswith(sent_text)
        ):
            return True
        return SequenceMatcher(None, sent_text, incoming_text).ratio() >= self.similarity_threshold

    def _normalize_text(self, text: Optional[Any]) -> str:
        return "\n".join(str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip().split())
