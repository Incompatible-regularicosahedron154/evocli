"""
Memory handlers — 记忆增删查、蒸馏、巩固、冲突检测。

新增 RPC (研究驱动):
  memory.smart_add       — MemRouter 决策后写入（自动分类+去重+冲突检测）
  memory.iterative_search — EviMem 迭代检索（证据缺口自动补充）
  memory.consolidate      — 情节→语义自动升格 (Memory Reflection Loop)
  memory.check_conflict   — 写入前冲突检测
  memory.forget_decayed   — 选择性遗忘 (ScrapMem 光学遗忘)
  memory.stats            — 记忆系统状态统计
"""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.handlers.memory")


def register(router) -> None:
    router.add("memory.add",              handle_memory_add)
    router.add("memory.search",           handle_memory_search)
    router.add("memory.constraints",      handle_memory_constraints)
    router.add("memory.distill",          handle_memory_distill)
    router.add("memory.recall",           handle_memory_recall)
    router.add("memory.write",            handle_memory_write)
    # ── 研究驱动新增 ────────────────────────────────────────────
    router.add("memory.smart_add",        handle_memory_smart_add)
    router.add("memory.iterative_search", handle_memory_iterative_search)
    router.add("memory.consolidate",      handle_memory_consolidate)
    router.add("memory.check_conflict",   handle_memory_check_conflict)
    router.add("memory.forget_decayed",   handle_memory_forget_decayed)
    router.add("memory.stats",            handle_memory_stats)


async def handle_memory_add(req_id: str, params: dict, send, state) -> None:
    content  = params.get("content", "")
    mem_type = params.get("type", "episodic")
    priority = params.get("priority", "project")
    try:
        memory  = state.get_memory()
        item_id = memory.add(content, memory_type=mem_type, priority=priority)
        await send.response(req_id, {"ok": True, "id": item_id or ""})
    except Exception as e:
        log.exception("memory.add failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_search(req_id: str, params: dict, send, state) -> None:
    query = params.get("query", "")
    top_k = params.get("top_k", 5)
    try:
        memory  = state.get_memory()
        results = memory.search(query, top_k=top_k)
        await send.response(req_id, results)
    except Exception as e:
        log.exception("memory.search failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_constraints(req_id: str, params: dict, send, state) -> None:
    try:
        memory      = state.get_memory()
        constraints = memory.get_constraints()
        await send.response(req_id, constraints)
    except Exception as e:
        log.exception("memory.constraints failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_distill(req_id: str, params: dict, send, state) -> None:
    try:
        from evocli_soul.memory_distill import MemoryDistiller
        distiller = MemoryDistiller(state.get_bridge())
        result    = await distiller.run(params)
        await send.response(req_id, result)
    except Exception as e:
        log.exception("memory.distill failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_recall(req_id: str, params: dict, send, state) -> None:
    query = params.get("query", "")
    top_k = int(params.get("top_k", 5))
    try:
        memory  = state.get_memory()
        results = memory.search(query, top_k=top_k)
        await send.response(req_id, results)
    except Exception as e:
        log.exception("memory.recall failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_write(req_id: str, params: dict, send, state) -> None:
    try:
        memory   = state.get_memory()
        content  = params.get("body", params.get("content", ""))
        priority = params.get("priority_scope", "project")
        item_id  = memory.add(content, memory_type=params.get("memory_type", "episodic"), priority=priority)
        await send.response(req_id, {"ok": True, "id": item_id or ""})
    except Exception as e:
        log.exception("memory.write failed")
        await send.error(req_id, -32603, str(e))


# ── 研究驱动新增 handlers ────────────────────────────────────────────────────

async def handle_memory_smart_add(req_id: str, params: dict, send, state) -> None:
    """
    MemRouter 智能写入: 自动决策是否值得写入、分类类型、检测冲突。
    
    Research: MemRouter (2026) — 用嵌入路由替代 LLM 做写入决策，降低延迟。
    EvoCLI: 规则层 + Jaccard 去重实现轻量版。

    params:
      content:   str   要写入的内容
      priority:  str   "project" | "tool" | "global"
      auto_type: bool  自动推断 memory_type (default True)
    """
    content  = params.get("content", "")
    priority = params.get("priority", "project")
    if not content:
        await send.error(req_id, -32600, "content is required")
        return
    try:
        memory = state.get_memory()
        from evocli_soul.memory_router import get_memory_router
        from evocli_soul.memory_enhance import ConflictDetector
        from evocli_soul.handlers.metrics import _classify_with_model

        router = get_memory_router()
        # 获取最近记忆用于去重判断
        recent = memory.get_all(limit=30)
        # Layer 0/1: 快速门控——拒绝/去重（规则引擎，同步，< 1ms）
        should, rule_type, rule_importance = router.should_memorize(content, recent)

        if not should:
            await send.response(req_id, {
                "ok":      False,
                "written": False,
                "reason":  "MemRouter: content not worth memorizing (duplicate or low value)",
                "memory_type": rule_type,
            })
            return

        # Layer 2: ML 分类器——精确类型分类（sklearn，< 5ms）
        # 优先使用已训练的 sklearn 模型；模型未就绪时回退到规则分类
        ml_result = _classify_with_model(content)
        if ml_result and ml_result.get("confidence", 0) >= 0.6:
            mem_type   = ml_result["label"]
            importance = float(ml_result.get("importance", rule_importance))
            classifier_source = "ml_model"
        else:
            mem_type   = rule_type
            importance = rule_importance
            classifier_source = "rule_engine"
        log.debug("MemRouter classify: %s [%s] confidence=%.2f",
                  mem_type, classifier_source, ml_result.get("confidence", 0) if ml_result else 0)

        # 冲突检测
        detector = ConflictDetector(memory._store)
        conflict  = detector.check_conflict(content, mem_type, memory.project_id)

        if conflict["action"] == "skip":
            await send.response(req_id, {
                "ok":      False,
                "written": False,
                "reason":  conflict["reason"],
                "conflict": conflict,
            })
            return

        # 写入
        mid = memory.add(content, memory_type=mem_type, priority=priority, importance=importance)

        # 降权冲突记忆 (Conflict-Driven Forgetting)
        if conflict["action"] == "replace" and conflict.get("conflicting_ids"):
            detector.resolve_conflict(conflict["conflicting_ids"])

        await send.response(req_id, {
            "ok":        True,
            "written":   True,
            "id":        mid,
            "memory_type":       mem_type,
            "importance":        importance,
            "classifier_source": classifier_source,
            "conflict":  conflict,
        })
    except Exception as e:
        log.exception("memory.smart_add failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_iterative_search(req_id: str, params: dict, send, state) -> None:
    """
    EviMem 迭代检索: 发现证据缺口时自动补充查询。
    
    Research: EviMem (2026) — IRIS 闭环迭代检索机制，
    通过充分性评估发现"证据缺口"并定向改写查询。
    在 LoCoMo 上显著提升时序和多跳问题准确率。

    params:
      query:          str   检索查询
      top_k:          int   返回数量 (default 5)
      max_iterations: int   最大迭代次数 (default 2)
    """
    query          = params.get("query", "")
    top_k          = int(params.get("top_k", 5))
    max_iterations = int(params.get("max_iterations", 2))
    if not query:
        await send.error(req_id, -32600, "query is required")
        return
    try:
        memory = state.get_memory()
        from evocli_soul.memory_enhance import IterativeRetriever
        retriever = IterativeRetriever(memory)
        results, meta = retriever.search_with_evidence_check(query, top_k, max_iterations)
        await send.response(req_id, {"results": results, "meta": meta})
    except Exception as e:
        log.exception("memory.iterative_search failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_consolidate(req_id: str, params: dict, send, state) -> None:
    """
    记忆巩固: 情节记忆自动升格为语义记忆 (Memory Reflection Loop).
    
    Research: 多篇论文共识 — 频繁访问的情节记忆应升格为语义记忆，
    类似人类睡眠期间的记忆巩固过程。

    params:
      dry_run: bool  True=仅统计不修改 (default False)
    """
    dry_run = params.get("dry_run", False)
    try:
        memory = state.get_memory()
        from evocli_soul.memory_enhance import MemoryConsolidator
        consolidator = MemoryConsolidator(memory._store)
        result = consolidator.consolidate(
            project_id=memory.project_id,
            dry_run=dry_run,
        )
        await send.response(req_id, {"ok": True, **result, "dry_run": dry_run})
    except Exception as e:
        log.exception("memory.consolidate failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_check_conflict(req_id: str, params: dict, send, state) -> None:
    """
    写入前冲突检测 (Conflict Resolution).
    
    Research: "Conflict-Driven Forgetting" — 新证据与旧记忆冲突时策略性更新旧记忆。
    时间戳优先: 新信息胜于旧信息（约束类记忆除外）。

    params:
      content:     str   待写入内容
      memory_type: str   记忆类型
    """
    content     = params.get("content", "")
    memory_type = params.get("memory_type", "episodic")
    try:
        memory   = state.get_memory()
        from evocli_soul.memory_enhance import ConflictDetector
        detector = ConflictDetector(memory._store)
        result   = detector.check_conflict(content, memory_type, memory.project_id)
        await send.response(req_id, result)
    except Exception as e:
        log.exception("memory.check_conflict failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_forget_decayed(req_id: str, params: dict, send, state) -> None:
    """
    选择性遗忘: 删除超过 min_days 未访问的情节记忆 (ScrapMem 光学遗忘思路).
    
    Research: "Learning to Forget -- Hierarchical Episodic Memory" (2026)
    — 自动遗忘不重要信息以控制记忆规模，保留有用信息。
    约束/语义记忆受保护，不会被自动删除。

    params:
      min_days: int   未访问天数阈值 (default 90)
      dry_run:  bool  True=仅统计不修改 (default True)
    """
    min_days = int(params.get("min_days", 90))
    dry_run  = params.get("dry_run", True)
    try:
        memory    = state.get_memory()
        forgotten = memory.forget_decayed(min_days=min_days, dry_run=dry_run)
        await send.response(req_id, {
            "ok":       True,
            "count":    len(forgotten),
            "ids":      forgotten,
            "dry_run":  dry_run,
            "min_days": min_days,
        })
    except Exception as e:
        log.exception("memory.forget_decayed failed")
        await send.error(req_id, -32603, str(e))


async def handle_memory_stats(req_id: str, params: dict, send, state) -> None:
    """
    记忆系统状态统计 (MemRouter 状态感知).
    
    Research: MemRouter 通过状态感知决定写入策略。
    Returns: 各类型记忆数量、衰减情况、项目 ID。
    """
    try:
        memory = state.get_memory()
        stats  = memory.get_memory_stats()
        await send.response(req_id, stats)
    except Exception as e:
        log.exception("memory.stats failed")
        await send.error(req_id, -32603, str(e))
