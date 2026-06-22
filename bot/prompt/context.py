"""Prompt 构建上下文类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PromptContext:
    """构建一次聊天 prompt 所需的上下文。"""

    user_message: str
    session_name: str
    persona: Optional[str] = None
    schedule_context: str = ""
    history: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptBuildResult:
    """Prompt 构建结果。"""

    messages: List[Dict[str, str]]
    stats: Dict[str, Any]
