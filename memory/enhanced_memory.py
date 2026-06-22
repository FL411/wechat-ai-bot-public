"""
Enhanced Memory System - 层级语义记忆系统
实现：语义记忆、重要性评分、定期摘要、智能遗忘、BM25混合召回、Context压缩
"""

import os
import json
import time
import re
import uuid
import math
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class MemoryItem:
    id: str
    content: str
    content_type: str
    importance: float
    created_at: float
    last_accessed: float
    access_count: int
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "content_type": self.content_type,
            "importance": self.importance,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "metadata": self.metadata,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        return cls(
            id=data["id"],
            content=data["content"],
            content_type=data.get("content_type", "general"),
            importance=data.get("importance", 0.5),
            created_at=data.get("created_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
        )


class BGEEmbedder:
    """BGE-m3 向量化模型 - 真正的语义嵌入
    使用 sentence-transformers 的 BAAI/bge-m3 模型
    首次使用时会自动下载模型（约 500MB）
    """

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model_name = model_name
        self.model = None
        self.dim = 1024
        self._load_model()

    def _load_model(self):
        import os

        try:
            import torch

            if not hasattr(torch.distributed, "is_initialized"):
                torch.distributed.is_initialized = lambda: False
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name, cache_folder="data/model_cache")
            self.dim = self.model.get_sentence_embedding_dimension()
        except Exception as e:
            err_str = str(e).lower()
            if any(
                x in err_str for x in ["ftfy", "ssl", "connection", "timeout", "network", "http"]
            ):
                print("[INFO] BGE 模型下载失败（网络问题），尝试离线模式...")
                try:
                    import torch

                    if not hasattr(torch.distributed, "is_initialized"):
                        torch.distributed.is_initialized = lambda: False
                    os.environ["HF_HUB_OFFLINE"] = "1"
                    from sentence_transformers import SentenceTransformer

                    self.model = SentenceTransformer(
                        self.model_name, cache_folder="data/model_cache"
                    )
                    self.dim = self.model.get_sentence_embedding_dimension()
                    print("[INFO] BGE 离线模式加载成功")
                except Exception as e2:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                    raise Exception(f"BGE 模型加载失败且无缓存: {e2}")
            else:
                raise Exception(f"BGE 模型加载失败: {e}")

    def encode(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dim
        embedding = self.model.encode(text, normalize_embeddings=True)
        emb_list = embedding.tolist()
        if isinstance(emb_list[0], list):
            return emb_list[0]
        return emb_list

    def cosine_sim(self, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return max(0.0, min(1.0, dot))


class SimpleEmbedder:
    """轻量级 Embedder - 基于关键词权重的伪语义向量化（备选方案）"""

    def __init__(self):
        self.dim = 128
        self._keyword_weights = {
            "偏好": 1.5,
            "喜欢": 1.5,
            "讨厌": 1.5,
            "想要": 1.3,
            "工作": 1.2,
            "学习": 1.2,
            "生活": 1.2,
            "问题": 1.1,
            "帮助": 1.1,
            "麻烦": 1.1,
            "情绪": 1.3,
            "开心": 1.3,
            "难过": 1.3,
            "生气": 1.3,
            "计划": 1.2,
            "目标": 1.2,
            "决定": 1.2,
        }

    def encode(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dim
        words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", text.lower())
        vec = [0.0] * self.dim
        for i, word in enumerate(words[: self.dim]):
            weight = self._keyword_weights.get(word, 1.0)
            vec[i % self.dim] += weight * hash(word) % 1000 / 1000.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def cosine_sim(self, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return max(0.0, min(1.0, dot))


class BM25:
    """BM25 关键词检索器 - 经典的文本检索算法"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs: Dict[str, int] = {}
        self.doc_lens: List[int] = []
        self.corpus_size = 0
        self.avgdl = 0
        self.corpus: List[str] = []
        self.doc_ids: List[str] = []

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text.lower())

    def _initialize(self, corpus: List[Tuple[str, str]]):
        self.corpus_size = len(corpus)
        self.corpus = []
        self.doc_ids = []
        self.doc_freqs = {}
        self.doc_lens = []
        total_len = 0

        for doc_id, doc_text in corpus:
            self.corpus.append(doc_text)
            self.doc_ids.append(doc_id)
            tokens = self._tokenize(doc_text)
            self.doc_lens.append(len(tokens))
            total_len += len(tokens)

            for token in set(tokens):
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        self.avgdl = total_len / self.corpus_size if self.corpus_size > 0 else 0

    def add_doc(self, doc_id: str, doc_text: str):
        tokens = self._tokenize(doc_text)
        self.corpus.append(doc_text)
        self.doc_ids.append(doc_id)
        self.doc_lens.append(len(tokens))
        self.corpus_size += 1

        for token in set(tokens):
            self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        self.avgdl = (self.avgdl * (self.corpus_size - 1) + len(tokens)) / self.corpus_size

    def remove_doc(self, doc_id: str):
        try:
            idx = self.doc_ids.index(doc_id)
            tokens = self._tokenize(self.corpus[idx])
            for token in set(tokens):
                if self.doc_freqs.get(token, 0) > 0:
                    self.doc_freqs[token] -= 1
            del self.corpus[idx]
            del self.doc_ids[idx]
            del self.doc_lens[idx]
            self.corpus_size -= 1
            if self.corpus_size > 0:
                self.avgdl = sum(self.doc_lens) / self.corpus_size
            else:
                self.avgdl = 0
        except ValueError:
            pass

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        if not self.corpus:
            return []

        query_tokens = self._tokenize(query)
        scores = []

        for i, doc_text in enumerate(self.corpus):
            doc_tokens = self._tokenize(doc_text)
            doc_len = self.doc_lens[i]
            doc_freq_map = {}

            for token in doc_tokens:
                doc_freq_map[token] = doc_freq_map.get(token, 0) + 1

            score = 0.0
            for q_token in query_tokens:
                if q_token not in doc_freq_map:
                    continue

                tf = doc_freq_map[q_token]
                df = self.doc_freqs.get(q_token, 0)

                idf = math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1)
                tf_component = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                )
                score += idf * tf_component

            scores.append((self.doc_ids[i], score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class HybridRetriever:
    """混合检索器 - Vector + BM25 + RRF 融合"""

    def __init__(self, embedder, use_bm25: bool = True, use_rerank: bool = True):
        self.embedder = embedder
        self.use_bm25 = use_bm25 and not isinstance(embedder, SimpleEmbedder)
        self.use_rerank = use_rerank
        self.bm25 = BM25() if self.use_bm25 else None
        self._bm25_initialized = False
        self._pending_bm25_items: Dict[str, MemoryItem] = {}

    def add_to_bm25(self, item: MemoryItem):
        if self.use_bm25 and item.content:
            if not self._bm25_initialized:
                self._pending_bm25_items[item.id] = item
            else:
                self.bm25.add_doc(item.id, item.content)

    def remove_from_bm25(self, item_id: str):
        if self.use_bm25 and hasattr(self.bm25, "remove_doc"):
            self.bm25.remove_doc(item_id)
        self._pending_bm25_items.pop(item_id, None)

    def initialize_bm25(self, items: List[MemoryItem]):
        if self.use_bm25 and items:
            corpus = [(item.id, item.content) for item in items if item.content]
            self.bm25._initialize(corpus)
            self._bm25_initialized = True
            self._pending_bm25_items.clear()

    def retrieve(
        self, query: str, items: List[MemoryItem], top_k: int = 5, session_id: Optional[str] = None
    ) -> List[MemoryItem]:
        item_map = {item.id: item for item in items}
        results_dict: Dict[str, Tuple[float, MemoryItem]] = {}

        vector_results = self._vector_search(query, items, session_id)
        for rank, (score, item) in enumerate(vector_results):
            results_dict[item.id] = (score, item)

        if self.use_bm25 and self._bm25_initialized:
            bm25_results = self.bm25.search(query, top_k=top_k * 2)
            for rank, (doc_id, score) in enumerate(bm25_results):
                if doc_id in item_map:
                    item = item_map[doc_id]
                    if session_id and item.metadata.get("session_id") != session_id:
                        continue
                    rrf_score = self._rrf_score(score, rank, k=60)
                    if doc_id in results_dict:
                        old_score, _ = results_dict[doc_id]
                        results_dict[doc_id] = (old_score + rrf_score, item)
                    else:
                        results_dict[doc_id] = (rrf_score, item)

        sorted_results = sorted(results_dict.values(), key=lambda x: x[0], reverse=True)
        return [item for _, item in sorted_results[:top_k]]

    def _vector_search(
        self, query: str, items: List[MemoryItem], session_id: Optional[str] = None
    ) -> List[Tuple[float, MemoryItem]]:
        if not items:
            return []

        query_emb = self.embedder.encode(query)
        candidates = []

        for item in items:
            if session_id and item.metadata.get("session_id") != session_id:
                continue
            if item.embedding:
                sim = self.embedder.cosine_sim(query_emb, item.embedding)
                age_days = (time.time() - item.created_at) / 86400
                time_boost = math.exp(-0.05 * age_days)
                final_score = sim * 0.8 + time_boost * 0.2 * item.importance
                candidates.append((final_score, item))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates

    def _rrf_score(self, score: float, rank: int, k: int = 60) -> float:
        return score / (k + rank)


class ContextCompressor:
    """Context 压缩器 - 让 LLM 压缩记忆上下文"""

    def __init__(self, llm_client=None, max_context_tokens: int = 500):
        self.llm_client = llm_client
        self.max_context_tokens = max_context_tokens

    def compress(self, memories: List[MemoryItem], current_query: str = "") -> str:
        if not memories:
            return ""

        if not self.llm_client:
            return self._rule_based_compress(memories)

        if hasattr(self.llm_client, "_client") and hasattr(self.llm_client._client, "_ready"):
            return self._smart_rule_based_compress(memories, current_query)

        memories_text = "\n".join(
            [
                f"[{i+1}] {item.content[:150]}" + ("..." if len(item.content) > 150 else "")
                for i, item in enumerate(memories)
            ]
        )

        prompt = f"""当前用户问题：{current_query}

以下是相关的记忆片段，请提炼出与当前问题最相关的 2-3 条关键信息，压缩为简洁的 1-2 句话：

{memories_text}

压缩后的关键记忆（直接输出，不要解释）：
"""

        try:
            result = self.llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_context_tokens,
            )
            return (result or "").strip()
        except Exception:
            return self._smart_rule_based_compress(memories, current_query)

    def _smart_rule_based_compress(
        self, memories: List[MemoryItem], current_query: str = ""
    ) -> str:
        if not memories:
            return ""

        query_lower = (current_query or "").lower()
        scored_memories = []
        for item in memories:
            score = item.importance
            content_lower = item.content.lower()
            for word in query_lower.split():
                if len(word) >= 2 and word in content_lower:
                    score += 0.3
            if item.content_type == "preference":
                score += 0.2
            elif item.content_type == "fact":
                score += 0.1
            scored_memories.append((score, item))

        scored_memories.sort(key=lambda x: x[0], reverse=True)
        top_items = [item for _, item in scored_memories[:3]]

        parts = []
        for item in top_items:
            preview = item.content[:80] + ("..." if len(item.content) > 80 else "")
            type_label = {"preference": "偏好", "fact": "事实", "summary": "摘要"}.get(
                item.content_type, ""
            )
            if type_label:
                parts.append(f"[{type_label}] {preview}")
            else:
                parts.append(preview)

        return "；".join(parts) if parts else ""

    def _rule_based_compress(self, memories: List[MemoryItem]) -> str:
        if not memories:
            return ""

        lines = []
        for item in memories[:3]:
            preview = item.content[:80] + ("..." if len(item.content) > 80 else "")
            lines.append(f"- {preview}")

        return "相关记忆：" + "; ".join(lines)


class SemanticMemory:
    """语义记忆 - 支持向量+BM25混合检索"""

    def __init__(
        self, storage_dir: str = "data/semantic_memory", use_bge: bool = True, use_bm25: bool = True
    ):
        self.storage_dir = storage_dir
        self.use_bge = use_bge
        os.makedirs(storage_dir, exist_ok=True)

        if use_bge:
            try:
                self.embedder = BGEEmbedder()
            except Exception as e:
                print(f"[WARN] BGE 模型加载失败，使用 SimpleEmbedder: {e}")
                self.embedder = SimpleEmbedder()
        else:
            self.embedder = SimpleEmbedder()

        self.hybrid_retriever = HybridRetriever(self.embedder, use_bm25=use_bm25)
        self.items: Dict[str, MemoryItem] = {}
        self._lock = Lock()
        self._load_index()

    def _load_index(self):
        index_file = os.path.join(self.storage_dir, "index.json")
        if os.path.exists(index_file):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item_data in data.get("items", []):
                        item = MemoryItem.from_dict(item_data)
                        self.items[item.id] = item
                self.hybrid_retriever.initialize_bm25(list(self.items.values()))
            except Exception:
                pass

    def _save_index(self):
        index_file = os.path.join(self.storage_dir, "index.json")
        with self._lock:
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"items": [item.to_dict() for item in self.items.values()]},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

    def delete_by_user(self, username: str):
        """删除指定用户的所有记忆"""
        with self._lock:
            to_delete = []
            for memory_id, item in self.items.items():
                if item.metadata.get("username") == username:
                    to_delete.append(memory_id)
            for memory_id in to_delete:
                del self.items[memory_id]
                self.hybrid_retriever.remove_from_bm25(memory_id)
            if to_delete:
                self._save_index()
                logger.info(f"[Memory] 删除用户 {username} 的 {len(to_delete)} 条记忆")

    def _rate_importance(self, content: str, content_type: str = "general") -> float:
        score = 0.5
        if content_type == "fact":
            score += 0.2
        if content_type == "preference":
            score += 0.25
        if content_type == "summary":
            score += 0.15

        length = len(content)
        if length > 50:
            score += 0.1
        if length > 200:
            score += 0.1

        if any(k in content for k in ["喜欢", "讨厌", "偏好", "想要", "决定", "计划"]):
            score += 0.15
        if any(k in content for k in ["？", "?", "为什么", "怎么", "如何"]):
            score -= 0.1

        return max(0.1, min(1.0, score))

    def add(
        self, content: str, content_type: str = "general", metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        memory_id = uuid.uuid4().hex
        now = time.time()
        embedding = self.embedder.encode(content)

        item = MemoryItem(
            id=memory_id,
            content=content,
            content_type=content_type,
            importance=self._rate_importance(content, content_type),
            created_at=now,
            last_accessed=now,
            access_count=0,
            metadata=metadata or {},
            embedding=embedding,
        )

        with self._lock:
            self.items[memory_id] = item

        self.hybrid_retriever.add_to_bm25(item)
        self._save_index()
        return memory_id

    def recall(
        self, query: str, top_k: int = 5, session_id: Optional[str] = None
    ) -> List[MemoryItem]:
        items_list = list(self.items.values())
        results = self.hybrid_retriever.retrieve(query, items_list, top_k, session_id)

        for item in results:
            item.access_count += 1
            item.last_accessed = time.time()

        if results:
            self._save_index()

        return results

    def get_recent(self, session_id: str, limit: int = 10) -> List[MemoryItem]:
        with self._lock:
            items = [
                item
                for item in self.items.values()
                if item.metadata.get("session_id") == session_id
            ]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:limit]

    def count(self) -> int:
        return len(self.items)


class ConversationSummarizer:
    """对话摘要器 - 定期将长对话压缩为摘要"""

    def __init__(self, llm_client=None, summary_interval: int = 15):
        self.llm_client = llm_client
        self.summary_interval = summary_interval
        self._pending_sessions: Dict[str, int] = {}

    def should_summarize(self, session_id: str, message_count: int) -> bool:
        return message_count >= self.summary_interval

    def _detect_topic_shift(self, messages: List[Dict]) -> bool:
        if len(messages) < 5:
            return False
        topics = []
        for msg in messages[-5:]:
            content = msg.get("content", "")[:100]
            if content:
                topics.append(content)
        unique_ratio = len(set(topics)) / len(topics) if topics else 1.0
        return unique_ratio > 0.7

    def summarize_conversation(self, messages: List[Dict[str, str]], session_id: str) -> str:
        if not self.llm_client:
            return self._rule_based_summary(messages)

        if hasattr(self.llm_client, "_client") and hasattr(self.llm_client._client, "_ready"):
            return self._smart_rule_based_summary(messages)

        conversation_text = "\n".join(
            [
                f"{'用户' if m.get('role') == 'user' else '助手'}: {m.get('content', '')[:200]}"
                for m in messages[-20:]
                if m.get("content")
            ]
        )

        prompt = f"""将以下对话总结为 3-5 句话的摘要，保留：
1. 话题主题
2. 用户关键信息（偏好、决定、问题等）
3. 助手的核心回应

对话内容：
{conversation_text}

摘要："""

        try:
            result = self.llm_client.chat(
                [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=300
            )
            return (result or "").strip()
        except Exception:
            return self._rule_based_summary(messages)

    def _rule_based_summary(self, messages: List[Dict]) -> str:
        if not messages:
            return "无对话记录"

        user_intents = []
        for msg in messages[-20:]:
            content = msg.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            if msg.get("role") == "user":
                if any(k in content for k in ["想", "要", "喜欢", "计划"]):
                    user_intents.append(content[:50])

        summary_parts = []
        if user_intents:
            summary_parts.append(f"用户表达了: {'; '.join(user_intents[:2])}")

        return " ".join(summary_parts) if summary_parts else "一般性对话"

    def _smart_rule_based_summary(self, messages: List[Dict]) -> str:
        if not messages:
            return "无对话记录"

        user_intents = []
        user_facts = []
        assistant_key_points = []

        for msg in messages[-20:]:
            content = msg.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."

            if msg.get("role") == "user":
                if any(k in content for k in ["想", "要", "喜欢", "计划", "希望"]):
                    user_intents.append(content[:60])
                if any(k in content for k in ["我叫", "我是", "我在", "我住", "我做", "我的工作"]):
                    user_facts.append(content[:50])
            else:
                if any(k in content for k in ["建议", "可以", "应该", "记得", "下次"]):
                    assistant_key_points.append(content[:60])

        summary_parts = []
        if user_facts:
            summary_parts.append(f"用户信息: {'; '.join(user_facts[:2])}")
        if user_intents:
            summary_parts.append(f"用户表达了: {'; '.join(user_intents[:2])}")
        if assistant_key_points:
            summary_parts.append(f"关键建议: {'; '.join(assistant_key_points[:1])}")

        return "。".join(summary_parts) if summary_parts else "一般性对话"


class MemoryDecay:
    """记忆衰减器 - 基于重要性、访问频率、时间自动淘汰低价值记忆"""

    def __init__(self, decay_rate: float = 0.1, min_score: float = 0.05):
        self.decay_rate = decay_rate
        self.min_score = min_score

    def compute_score(self, item: MemoryItem) -> float:
        age_days = (time.time() - item.created_at) / 86400
        access_boost = math.log(1 + item.access_count) * 0.2
        base_score = item.importance * math.exp(-self.decay_rate * age_days)
        return max(self.min_score, base_score + access_boost)

    def should_evict(self, item: MemoryItem) -> bool:
        return self.compute_score(item) < self.min_score

    def get_eviction_candidates(self, items: List[MemoryItem], max_items: int = 500) -> List[str]:
        if len(items) <= max_items:
            return []

        scored = [(self.compute_score(item), item.id) for item in items]
        scored.sort(key=lambda x: x[0])
        return [item_id for _, item_id in scored[: len(items) - max_items]]


class EnhancedMemoryManager:
    """增强记忆管理器 - 整合语义记忆、BM25混合召回、摘要、衰减、Context压缩"""

    def __init__(
        self,
        data_dir: str = "data/sessions",
        memory_dir: str = "data/memory",
        semantic_dir: str = "data/semantic_memory",
        llm_client=None,
        summary_interval: int = 15,
        max_semantic_items: int = 500,
        use_bge: bool = True,
        use_bm25: bool = True,
        use_compression: bool = True,
    ):
        self.semantic_memory = SemanticMemory(
            storage_dir=semantic_dir, use_bge=use_bge, use_bm25=use_bm25
        )
        self.summarizer = ConversationSummarizer(llm_client, summary_interval)
        self.decay = MemoryDecay()
        self.max_semantic_items = max_semantic_items
        self.llm_client = llm_client
        self.use_compression = use_compression and llm_client is not None

        self.compressor = ContextCompressor(llm_client) if self.use_compression else None

        self.data_dir = data_dir
        self.memory_dir = memory_dir
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(memory_dir, exist_ok=True)
        os.makedirs(semantic_dir, exist_ok=True)

        self._session_msg_counts: Dict[str, int] = {}
        self._pending_summaries: Dict[str, List[Dict]] = {}

    def record_interaction(
        self, session_id: str, user_text: str, assistant_text: str = "", is_important: bool = False
    ):
        metadata = {"session_id": session_id, "timestamp": datetime.now().isoformat()}

        if is_important or self._is_significant_content(user_text):
            self.semantic_memory.add(
                content=user_text, content_type="user_input", metadata=metadata
            )

        if assistant_text and len(assistant_text) > 20:
            self.semantic_memory.add(
                content=assistant_text,
                content_type="assistant_response",
                metadata={**metadata, "user_query": user_text[:100]},
            )

        if session_id not in self._session_msg_counts:
            self._session_msg_counts[session_id] = 0
        self._session_msg_counts[session_id] += 1

        if session_id not in self._pending_summaries:
            self._pending_summaries[session_id] = []
        self._pending_summaries[session_id].append({"role": "user", "content": user_text})
        if assistant_text:
            self._pending_summaries[session_id].append(
                {"role": "assistant", "content": assistant_text}
            )

        msg_count = self._session_msg_counts[session_id]
        if self.summarizer.should_summarize(session_id, msg_count):
            self._run_summary(session_id)

        self._run_decay()

    def delete_memory_by_user(self, username: str):
        """删除指定用户的所有记忆"""
        self.semantic_memory.delete_by_user(username)
        logger.info(f"[EnhancedMemory] 用户 {username} 的记忆已清空")

    def _is_significant_content(self, text: str) -> bool:
        significant_keywords = [
            "喜欢",
            "讨厌",
            "偏好",
            "想要",
            "决定",
            "计划",
            "工作",
            "学习",
            "目标",
            "困难",
            "帮助",
            "谢谢",
            "对不起",
            "抱歉",
        ]
        return any(k in text for k in significant_keywords) or len(text) > 100

    def _run_summary(self, session_id: str):
        messages = self._pending_summaries.get(session_id, [])
        if len(messages) < 10:
            return

        summary_text = self.summarizer.summarize_conversation(messages, session_id)
        if summary_text:
            self.semantic_memory.add(
                content=summary_text,
                content_type="summary",
                metadata={
                    "session_id": session_id,
                    "message_count": len(messages),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            self._pending_summaries[session_id] = messages[-10:]

    def _run_decay(self):
        items = list(self.semantic_memory.items.values())
        evict_ids = self.decay.get_eviction_candidates(items, self.max_semantic_items)
        if evict_ids:
            for item_id in evict_ids:
                del self.semantic_memory.items[item_id]
            self.semantic_memory._save_index()

    def build_context(self, session_id: str, current_query: str, max_items: int = 5) -> str:
        semantic_memories = self.semantic_memory.recall(
            current_query, top_k=max_items, session_id=session_id
        )

        logger.info(
            f"[DEBUG] build_context: session_id={session_id}, query={current_query[:50]}, memories_count={len(semantic_memories)}"
        )
        for m in semantic_memories:
            logger.info(
                f"[DEBUG] memory item: session={m.metadata.get('session_id')}, content={m.content[:50]}"
            )

        if not semantic_memories:
            return ""

        if self.use_compression and self.compressor:
            compressed = self.compressor.compress(semantic_memories, current_query)
            if compressed:
                return f"【相关记忆】: {compressed}"

        lines = ["【相关记忆】:"]
        for item in semantic_memories:
            type_label = {
                "summary": "摘要",
                "fact": "事实",
                "preference": "偏好",
                "user_input": "用户表达",
                "assistant_response": "助手回复",
            }.get(item.content_type, "记忆")

            content_preview = item.content[:100]
            if len(item.content) > 100:
                content_preview += "..."
            lines.append(f"- [{type_label}] {content_preview}")

        return "\n".join(lines)

    def get_user_profile_summary(self, session_id: str) -> str:
        recent_items = self.semantic_memory.get_recent(session_id, limit=20)

        preferences = []
        summaries = []

        for item in recent_items:
            if item.content_type == "preference":
                preferences.append(item.content[:80])
            elif item.content_type == "summary":
                summaries.append(item.content[:100])

        lines = []
        if preferences:
            lines.append(f"用户偏好: {'; '.join(preferences[:3])}")
        if summaries:
            lines.append(f"近期话题摘要: {'; '.join(summaries[:2])}")

        return "\n".join(lines) if lines else ""

    def get_stats(self) -> Dict[str, Any]:
        return {
            "semantic_memory_count": self.semantic_memory.count(),
            "max_items": self.max_semantic_items,
            "embedder_type": type(self.semantic_memory.embedder).__name__,
            "session_counts": dict(self._session_msg_counts),
        }
