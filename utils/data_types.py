from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime
from enum import IntEnum


class MessageType(IntEnum):
    """微信消息类型"""

    TEXT = 1  # 文本消息
    IMAGE = 3  # 图片消息
    VOICE = 34  # 语音消息
    VIDEO = 43  # 视频消息
    EMOJI = 47  # 表情消息
    LOCATION = 48  # 位置消息
    LINK = 49  # 链接消息
    FILE = 49  # 文件消息
    SYSTEM = 10000  # 系统消息


@dataclass
class Message:
    role: str
    content: str
    timestamp: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Message":
        return cls(
            role=data.get("role", ""),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class Session:
    session_id: str
    created_at: str = ""
    last_active: str = ""
    messages: List[Message] = field(default_factory=list)
    max_history: int = 20
    script: str = ""
    script_stage: str = "Phase_1"
    script_updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.last_active:
            self.last_active = self.created_at

    def add_message(self, role: str, content: str):
        msg = Message(role=role, content=content, timestamp=datetime.now().isoformat())
        self.messages.append(msg)
        self.last_active = datetime.now().isoformat()

        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history :]

    def get_messages(self) -> List[Dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self.messages]

    def set_script(self, script_content: str, stage: str = "Phase_1"):
        self.script = script_content
        self.script_stage = stage
        self.script_updated_at = datetime.now().isoformat()
        self.last_active = datetime.now().isoformat()

    def update_script_stage(self, stage: str):
        self.script_stage = stage
        self.script_updated_at = datetime.now().isoformat()
        self.last_active = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "messages": [m.to_dict() for m in self.messages],
            "script": self.script,
            "script_stage": self.script_stage,
            "script_updated_at": self.script_updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            created_at=data.get("created_at", ""),
            last_active=data.get("last_active", ""),
            messages=messages,
            max_history=data.get("max_history", 20),
            script=data.get("script", ""),
            script_stage=data.get("script_stage", "Phase_1"),
            script_updated_at=data.get("script_updated_at", ""),
        )
