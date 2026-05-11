# handlers/__init__.py — 导出所有 handler 注册函数
from evocli_soul.handlers.tracer       import register as register_tracer
from evocli_soul.handlers.agent        import register as register_agent
from evocli_soul.handlers.memory       import register as register_memory
from evocli_soul.handlers.skill        import register as register_skill
from evocli_soul.handlers.session      import register as register_session
from evocli_soul.handlers.system       import register as register_system
from evocli_soul.handlers.diff         import register as register_diff
from evocli_soul.handlers.edit         import register as register_edit
from evocli_soul.handlers.session_ext  import register as register_session_ext
from evocli_soul.handlers.web          import register as register_web
from evocli_soul.handlers.watch        import register as register_watch
from evocli_soul.handlers.knowledge    import register as register_knowledge
from evocli_soul.handlers.metrics      import register as register_metrics    # system.stats + evolution.transfer + mem_router
from evocli_soul.handlers.mcp_bridge    import register as register_mcp_bridge
from evocli_soul.handlers.code_analysis import register as register_code_analysis  # 迁移自 Rust: assume.*/impact.*/equiv.*/verify.*/symbol.usages/ranked_context
from evocli_soul.orchestrator           import register as register_orchestrator

def register_all(router) -> None:
    register_tracer(router)
    register_agent(router)
    register_memory(router)
    register_skill(router)
    register_session(router)
    register_system(router)
    register_diff(router)
    register_edit(router)
    register_session_ext(router)
    register_web(router)
    register_watch(router)
    register_knowledge(router)
    register_metrics(router)        # system.stats + evolution.transfer + mem_router.*
    register_mcp_bridge(router)
    register_code_analysis(router)  # assume.*/impact.*/equiv.*/verify.*/symbol.usages/ranked_context
    register_orchestrator(router)
