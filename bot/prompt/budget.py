"""Prompt 字符预算裁剪工具。"""

from __future__ import annotations

from typing import Dict, List, Tuple


def text_len(value: str) -> int:
    return len(value or "")


def message_chars(messages: List[Dict[str, str]]) -> int:
    return sum(text_len(item.get("content", "")) for item in messages)


def trim_text(text: str, max_chars: int, from_end: bool = False) -> Tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(text)
    if len(text or "") <= max_chars:
        return text or "", False
    if from_end:
        return ("..." + text[-max_chars:]).strip(), True
    return (text[:max_chars] + "...").strip(), True


def trim_history(
    messages: List[Dict[str, str]], max_chars: int, recent_count: int
) -> Tuple[List[Dict[str, str]], bool]:
    if not messages or max_chars <= 0 or recent_count <= 0:
        return [], bool(messages)

    candidates = messages[-recent_count:]
    kept_reversed: List[Dict[str, str]] = []
    total = 0
    trimmed = len(messages) > len(candidates)

    for item in reversed(candidates):
        content = str(item.get("content", ""))
        cost = len(content)
        if kept_reversed and total + cost > max_chars:
            trimmed = True
            break
        if not kept_reversed and cost > max_chars:
            clipped, _ = trim_text(content, max_chars, from_end=True)
            kept_reversed.append({"role": item.get("role", "user"), "content": clipped})
            trimmed = True
            break
        kept_reversed.append({"role": item.get("role", "user"), "content": content})
        total += cost

    return list(reversed(kept_reversed)), trimmed


def enforce_total_budget(
    system_message: Dict[str, str],
    history_messages: List[Dict[str, str]],
    user_message: Dict[str, str],
    max_total_chars: int,
) -> Tuple[List[Dict[str, str]], bool]:
    messages = [system_message, *history_messages, user_message]
    if message_chars(messages) <= max_total_chars:
        return messages, False

    trimmed = False
    history = history_messages[:]
    while history and message_chars([system_message, *history, user_message]) > max_total_chars:
        history.pop(0)
        trimmed = True

    remaining = max_total_chars - message_chars([*history, user_message])
    if remaining < len(system_message.get("content", "")):
        clipped, _ = trim_text(system_message.get("content", ""), max(remaining, 500))
        system_message = {"role": "system", "content": clipped}
        trimmed = True

    return [system_message, *history, user_message], trimmed
