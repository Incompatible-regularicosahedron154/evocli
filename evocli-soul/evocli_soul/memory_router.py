"""
memory_router.py — 记忆写入决策器 (MemRouter 思路)

研究来源: MemRouter (2026) - "Memory-as-Embedding Routing for Long-Term Conversational Agents"
  - 用嵌入路由替代逐轮 LLM 生成式记忆管理
  - 仅训练 ~12M 参数判断哪些轮次应写入外部记忆
  - 在保持检索管线不变的条件下显著降低记忆管理延迟

EvoCLI 轻量实现:
  - 规则层: 关键词信号 (快, 精确)
  - 嵌入层: 相似度去重 (避免写入重复记忆)
  - 信息密度层: 短句/通用回复不写入

三层决策:
  REJECT (不写入) → DEDUPLICATE (相似已存在) → ACCEPT (写入，并分类)
"""
from __future__ import annotations

import re
from typing import Optional

# ── 关键词信号 ────────────────────────────────────────────────────────────────

# 强信号: 一定要写入
# Bug D fix: 单字「要」会误匹配「需要」「重要」「主要」等高频词（false positive rate ~50%）
# 改为多字复合词模式，避免子串匹配污染中文文本。
# 同理：「请」误匹配「申请」「邀请」；uses? 加词边界防止匹配 user/useful。
_CONSTRAINT_SIGNALS  = r"(?:must(?:n't)?|never|always|禁止|必须|不能|严禁|要求|规定|一定要|不得不|强制)"
_PREFERENCE_SIGNALS  = r"(?:prefer(?:ence)?|\blike\b|偏好|喜欢|优先|倾向|希望|最好|建议使用|推荐)"
_SEMANTIC_SIGNALS    = r"(?:\bis\b|\bare\b|\buses?\b|版本|配置|架构|设计|原因|因为|所以|用于|基于)"
_PROCEDURAL_SIGNALS  = r"(?:how to|步骤|方法|先.{1,20}再|流程|过程|教程|使用方式)"

# 弱信号: 不确定
_EPISODIC_SIGNALS    = r"(?:今天|刚才|当时|上次|这次|本次|已经|完成|修复|done|fixed)"

# 拒绝信号: 不写入
_REJECT_SIGNALS      = r"(?:^好的?$|^ok$|^是的?$|^明白$|^知道了?$|^谢谢$|^thanks?$)"
_MIN_CONTENT_WORDS   = 4    # 少于4词的回复不写入
_MAX_SIMILAR_SCORE   = 0.92 # 相似度高于此阈值视为重复


class MemoryRouter:
    """
    决策器：判断一段内容是否值得写入长期记忆，以及应写为什么类型。
    
    研究: MemRouter 核心思路是用轻量模型替代 LLM 做写入决策，
    降低延迟同时避免"写入噪声"导致记忆质量下降。
    """

    def should_memorize(
        self,
        content: str,
        existing_memories: Optional[list[dict]] = None,
    ) -> tuple[bool, str, float]:
        """
        决策是否写入记忆。

        Returns:
            (should_write, memory_type, importance)
        """
        content = content.strip()

        # Layer 1: 明确拒绝 (空内容/通用回应)
        if not content:
            return False, "episodic", 0.0

        # Bug fix: 中文没有词间空格，用字符数而非词数判断长度
        # Chinese: min 5 chars; English: min 4 space-separated words
        is_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in content)
        if is_chinese:
            if len(content) < 5:
                return False, "episodic", 0.0
        else:
            if len(content.split()) < _MIN_CONTENT_WORDS:
                return False, "episodic", 0.0

        if re.search(_REJECT_SIGNALS, content, re.IGNORECASE):
            return False, "episodic", 0.0

        # Layer 2: 相似去重
        if existing_memories:
            if self._is_duplicate(content, existing_memories):
                return False, "episodic", 0.0

        # Layer 3: 分类并评分
        return self._classify_and_score(content)

    def _classify_and_score(self, content: str) -> tuple[bool, str, float]:
        """按信号强度分类记忆类型并给重要性评分。"""
        c = content.lower()

        # Constraint: 最高优先级，最高重要性
        if re.search(_CONSTRAINT_SIGNALS, c, re.IGNORECASE):
            return True, "constraint", 1.0

        # Preference: 高重要性
        if re.search(_PREFERENCE_SIGNALS, c, re.IGNORECASE):
            return True, "preference", 0.85

        # Procedural: 技能/步骤 — 高重要性
        if re.search(_PROCEDURAL_SIGNALS, c, re.IGNORECASE):
            return True, "procedural", 0.80

        # Semantic: 事实/知识 — 中高重要性
        if re.search(_SEMANTIC_SIGNALS, c, re.IGNORECASE):
            return True, "semantic", 0.70

        # Episodic: 具体事件 — 中等重要性，会随时间衰减
        if re.search(_EPISODIC_SIGNALS, c, re.IGNORECASE):
            return True, "episodic", 0.50

        # 较长内容默认情节记忆
        # Fix Bug B: Chinese has no word spaces — use character count, not word count
        is_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in content)
        content_len = len(content) if is_chinese else len(content.split())
        if content_len >= 10:
            return True, "episodic", 0.40

        # 其他: 不写入
        return False, "episodic", 0.0

    def _is_duplicate(self, content: str, existing: list[dict]) -> bool:
        """
        轻量去重: 基于词/字符重叠比率（Jaccard similarity）。
        中文无词间空格 → 用字符 bigram（从去空格后的字符串切片），英文用空格分词。
        论文 MemRouter 使用嵌入相似度，EvoCLI 使用轻量重叠作为 fallback。
        """
        def tokenize(text: str) -> set:
            text = text.lower().strip()
            # Detect Chinese (any CJK codepoint)
            if any("\u4e00" <= ch <= "\u9fff" for ch in text):
                # Fix Bug A: filter spaces first, then slice the CLEAN string (not original)
                clean = "".join(ch for ch in text if not ch.isspace())
                return set(clean[i:i+2] for i in range(len(clean) - 1)) or set(clean)
            else:
                return set(text.split())

        tokens_new = tokenize(content)
        for mem in existing[-20:]:  # 只检查最近20条
            text = (mem.get("body") or mem.get("title") or "")
            tokens_old = tokenize(text)
            if not tokens_new or not tokens_old:
                continue
            intersection = tokens_new & tokens_old
            union = tokens_new | tokens_old
            jaccard = len(intersection) / len(union) if union else 0
            if jaccard > _MAX_SIMILAR_SCORE:
                return True
        return False

    def batch_filter(
        self,
        turns: list[str],
        existing_memories: Optional[list[dict]] = None,
    ) -> list[tuple[str, str, float]]:
        """
        批量决策多条内容。
        Returns: [(content, memory_type, importance)] for content that should be memorized.
        """
        results = []
        for content in turns:
            should, mtype, importance = self.should_memorize(content, existing_memories)
            if should:
                results.append((content, mtype, importance))
        return results


# 全局单例
_router: Optional[MemoryRouter] = None


def get_memory_router() -> MemoryRouter:
    global _router
    if _router is None:
        _router = MemoryRouter()
    return _router
