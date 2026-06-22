"""角色人设加载器。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class PersonaProfile:
    """角色人设数据。"""

    key: str
    name: str
    identity: str = ""
    setting: str = ""
    exists: bool = False


class PersonaLoader:
    """从角色目录加载角色人设。"""

    def __init__(self, persona_dir: str):
        self.persona_dir = os.path.abspath(persona_dir)

    def list_personas(self) -> List[str]:
        if not os.path.isdir(self.persona_dir):
            return []
        names = []
        for item in os.listdir(self.persona_dir):
            path = os.path.join(self.persona_dir, item)
            if os.path.isdir(path):
                names.append(item)
        return sorted(names)

    def choose_default(self, preferred: Optional[str] = None) -> str:
        names = self.list_personas()
        if preferred and preferred in names:
            return preferred
        non_examples = [name for name in names if "示例" not in name]
        if non_examples:
            return non_examples[0]
        if names:
            return names[0]
        return "小明"

    def load(self, persona: Optional[str] = None) -> PersonaProfile:
        key = self.choose_default(persona)
        path = os.path.join(self.persona_dir, key)
        if not os.path.isdir(path):
            return PersonaProfile(key=key, name=key or "小明", exists=False)

        identity = self._read_text(os.path.join(path, "identity.txt"))
        setting = self._read_first_text(path, ["persona.md", "角色设定.md"])
        return PersonaProfile(
            key=key,
            name=key,
            identity=identity,
            setting=setting,
            exists=True,
        )

    def as_legacy_personas(self) -> Dict[str, Dict[str, str]]:
        """提供给旧命令逻辑使用的轻量角色字典。"""
        personas: Dict[str, Dict[str, str]] = {}
        for name in self.list_personas():
            profile = self.load(name)
            personas[name] = {
                "name": profile.name,
                "prompt": "\n\n".join(part for part in [profile.identity, profile.setting] if part),
                "description": profile.identity or profile.setting[:120],
            }
        return personas

    def _read_first_text(self, base_path: str, names: List[str]) -> str:
        for name in names:
            text = self._read_text(os.path.join(base_path, name))
            if text:
                return text
        return ""

    def _read_text(self, path: str) -> str:
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as file:
                return file.read().strip()
        except OSError:
            return ""
