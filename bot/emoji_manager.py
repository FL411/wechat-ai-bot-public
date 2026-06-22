"""
智能表情包管理系统
基于情绪识别自动发送合适的表情包
"""

import os
import random
import logging
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EMOTION_KEYWORDS: Dict[str, List[str]] = {
    "happy": [
        "开心",
        "高兴",
        "哈哈",
        "哈哈哈",
        "真好",
        "太棒了",
        "太开心",
        "笑死",
        "好开心",
        "嘿嘿",
        "嘻嘻",
        "美滋滋",
        "爽",
        "完美",
        "nice",
        "开心",
        "兴奋",
        "哇塞",
        "耶",
        "棒",
        "点赞",
        "good",
        "好耶",
        "奥利给",
        "冲",
        "绝了",
    ],
    "sad": [
        "难过",
        "伤心",
        "哭",
        "好累",
        "累死了",
        "累",
        "心塞",
        "郁闷",
        "不开心",
        "sad",
        "委屈",
        "失落",
        "灰心",
        "沮丧",
        "烦",
        "烦死了",
    ],
    "loved": [
        "想你",
        "爱你",
        "喜欢",
        "么么哒",
        "亲亲",
        "抱抱",
        "摸摸头",
        "心疼",
        "撒娇",
        "可爱",
        "啾咪",
        "比心",
        "甜甜",
        "love",
        "爱了",
        "好喜欢",
        "老公",
        "老婆",
    ],
    "tired": [
        "困",
        "好困",
        "想睡",
        "睡了",
        "累",
        "好累",
        "困了",
        "打哈欠",
        "没精神",
        "好累",
        "疲惫",
        "困死了",
        "困死",
        "困死了",
    ],
    "angry": [
        "生气",
        "气死",
        "烦",
        "讨厌",
        "滚",
        "烦死了",
        "无语",
        "cao",
        "草",
        "妈的",
        "卧槽",
        "气死我了",
        "愤怒",
        "恼火",
        "不爽",
        "生气",
    ],
    "surprised": [
        "哇",
        "哇塞",
        "卧槽",
        "真的假的",
        "惊呆了",
        "震惊",
        "震惊",
        "什么",
        "真的",
        "假的",
    ],
    "confused": [
        "啥",
        "啥意思",
        "不懂",
        "懵逼",
        "蒙",
        "不懂",
        "啥情况",
        "为什么",
        "为啥",
        "咋回事",
        "怎么回事",
        "咋了",
    ],
    "evasive": ["随便", "都行", "无所谓", "不知道", "没想好", "嗯", "哦", "好吧"],
    "reminded": ["记得", "别忘了", "提醒", "提醒我", "要记得", "记得提醒"],
    "neutral": [],
}


class EmojiManager:
    def __init__(self, emoji_dir: str = None):
        self.emoji_dir = str(PROJECT_ROOT / "emojis" if emoji_dir is None else Path(emoji_dir))
        self.categories = self._load_categories()
        self.enabled = True
        self.send_probability = 1.0  # 测试模式：100%发送

    def _load_categories(self) -> Dict[str, List[str]]:
        categories = {}
        if os.path.exists(self.emoji_dir):
            for item in os.listdir(self.emoji_dir):
                item_path = os.path.join(self.emoji_dir, item)
                if os.path.isdir(item_path):
                    emoji_files = [
                        f
                        for f in os.listdir(item_path)
                        if f.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".webp"))
                    ]
                    if emoji_files:
                        categories[item] = emoji_files
        logger.info(f"[表情] 已加载 {len(categories)} 个情绪分类")
        for cat, files in categories.items():
            logger.debug(f"[表情] {cat}: {len(files)} 张")
        return categories

    def should_send_emoji(self) -> bool:
        if not self.enabled:
            return False
        return random.random() < self.send_probability

    def detect_emotion(self, text: str) -> Optional[str]:
        if not text:
            return None

        text_lower = text.lower()
        emotion_scores: Dict[str, float] = {}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 1
            if score > 0:
                emotion_scores[emotion] = score

        import re

        for pattern, emotion, weight in [
            (r"！{2,}", "happy", 2),
            (r"哈{2,}", "happy", 2),
            (r"好{1,3}啊+", "happy", 2),
            (r"笑{1,3}死", "happy", 3),
            (r"啥.{0,3}事", "happy", 2),
            (r"好事", "happy", 2),
            (r"快说.{1,5}说", "happy", 2),
            (r"？？+", "confused", 2),
            (r"真的[吗?？]", "surprised", 2),
            (r"不是吧", "surprised", 2),
            (r"呜呜", "sad", 2),
            (r"好[吗?？]", "neutral", 1),
            (r"[吗?？]$", "neutral", 1),
        ]:
            if re.search(pattern, text_lower):
                current = emotion_scores.get(emotion, 0)
                emotion_scores[emotion] = current + weight

        emoji_map = {
            "😆": "happy",
            "😂": "happy",
            "🤣": "happy",
            "😊": "happy",
            "😢": "sad",
            "😭": "sad",
            "🥺": "sad",
            "😍": "loved",
            "🥰": "loved",
            "💕": "loved",
            "😴": "tired",
            "😫": "tired",
            "🥱": "tired",
            "😡": "angry",
            "😤": "angry",
            "😮": "surprised",
            "🤯": "surprised",
            "😕": "confused",
            "🙄": "confused",
        }
        for emoji, emotion in emoji_map.items():
            if emoji in text:
                emotion_scores[emotion] = emotion_scores.get(emotion, 0) + 2

        exclamation_count = text.count("!") + text.count("！")
        if exclamation_count >= 2:
            emotion_scores["happy"] = emotion_scores.get("happy", 0) + exclamation_count

        if not emotion_scores:
            return None

        best_emotion = max(emotion_scores.items(), key=lambda x: x[1])
        detected_emotion = best_emotion[0]
        score = best_emotion[1]

        logger.debug(f"[表情] 情绪识别: {detected_emotion} (得分: {score})")
        return detected_emotion

    def select_emoji(self, emotion: str) -> Optional[str]:
        if emotion not in self.categories:
            logger.debug(f"[表情] 情绪 '{emotion}' 无对应表情包")
            return None

        emoji_files = self.categories[emotion]
        if not emoji_files:
            return None

        selected = random.choice(emoji_files)
        emoji_path = os.path.join(self.emoji_dir, emotion, selected)
        logger.debug(f"[表情] 选择分类: {emotion} (共{len(emoji_files)}张) → {selected}")
        return emoji_path

    def get_random_emoji(self) -> Optional[str]:
        if not self.categories:
            return None

        emotion = random.choice(list(self.categories.keys()))
        return self.select_emoji(emotion)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        logger.info(f"[表情] 表情包功能 {'开启' if enabled else '关闭'}")

    def set_probability(self, prob: float):
        self.send_probability = max(0.0, min(1.0, prob))
        logger.info(f"[表情] 发送概率设置为 {self.send_probability:.0%}")

    def get_status(self) -> Dict:
        return {
            "enabled": self.enabled,
            "probability": self.send_probability,
            "categories": {k: len(v) for k, v in self.categories.items()},
            "total": sum(len(v) for v in self.categories.values()),
        }
