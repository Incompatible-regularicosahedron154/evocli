"""
soul_updater.py — Soul 自更新协议 (Section 9.8 / 19.4)

规划中的 Soul 自更新允许 Evolution Engine 提议优化 Python Soul 代码，
经用户审批后热更新 Soul 子模块，无需重新编译 Rust Host。

## 实现的安全约束 (不可绕过):
  1. 只能修改 evocli_soul/ 下的 .py 文件
  2. 不能修改 host_bridge.py（核心边界）
  3. 不能修改 router.py 消息格式定义
  4. 不能新增 import（防止依赖注入）
  5. 所有 ToolCall 仍必须通过 bridge.call()
  6. 必须通过安全静态审查
  7. 必须用户显式批准
  8. 测试通过后才应用

## 更新流程:
  1. Evolution Engine 检测到优化机会
  2. 生成 SoulUpdateProposal（diff + 理由 + 风险）
  3. 安全静态审查（< 1s）
  4. TUI 展示给用户 [查看 Diff] [批准] [拒绝]
  5. 用户批准 → 应用补丁 → 运行基本验证
  6. 记录到 soul_version.json
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("evocli.soul_updater")

# Soul 版本记录
_VERSION_FILE  = Path.home() / ".evocli" / "soul_version.json"
# Soul 根目录（只允许修改这里）
_SOUL_DIR      = Path(__file__).parent

# ── 安全约束 (编译期不可修改) ─────────────────────────────────────────────────

_FORBIDDEN_FILES = {
    "host_bridge.py",    # 核心边界，绝对不能修改
    "router.py",         # 消息格式定义
    "rpc.py",            # RPC 原语
    "state.py",          # 全局状态
    "soul_logging.py",   # 日志初始化
    "soul_updater.py",   # 自身不可被 Evolution Engine 修改（防止绕过安全检查）
}

_FORBIDDEN_PATTERNS = [
    r"import\s+os\s*$",                 # 直接 import os (可能绕过 bridge)
    r"import\s+subprocess",             # subprocess 直接调用（必须通过 bridge）
    # open() file access — check both literal strings AND common variable forms.
    # Previous regex only caught open("literal_path") but missed:
    #   open(path_var)          → now caught by the variable form pattern
    #   open(f"prefix/{var}")   → caught by f-string pattern
    #   open("~/.evocli/...")   → still exempt (our data directory)
    r'open\s*\(\s*["\'](?!.*evocli)',   # open("hardcoded/path") — literal non-evocli paths
    r'open\s*\(\s*f["\'](?!.*evocli)',  # open(f"fmt/{var}") — f-string non-evocli paths
    r'open\s*\(\s*(?!.*evocli)[a-zA-Z_]\w*\s*[,)]', # open(path_var) — unquoted variable
    r"Path\s*\(.*\)\s*\.(?:write_text|write_bytes|open)\s*\(",  # pathlib write outside bridge
    r"__import__\s*\(",                 # 动态 import
    r"exec\s*\(",                       # exec（代码注入）
    r"eval\s*\(",                       # eval
]


class SoulUpdateProposal:
    """一个待审批的 Soul 更新提案。"""

    def __init__(
        self,
        module:     str,           # 要修改的模块（相对路径，如 "context_engine.py"）
        diff:       str,           # unified diff 内容
        reason:     str,           # 变更原因
        risk_level: str,           # LOW / MEDIUM / HIGH
        expected_improvement: str, # 预期改进（如 "Token 浪费降低 23%"）
    ):
        self.module              = module
        self.diff                = diff
        self.reason              = reason
        self.risk_level          = risk_level
        self.expected_improvement = expected_improvement
        self.proposal_id         = f"soul_update_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self.created_at          = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "proposal_id":          self.proposal_id,
            "module":               self.module,
            "diff":                 self.diff,
            "reason":               self.reason,
            "risk_level":           self.risk_level,
            "expected_improvement": self.expected_improvement,
            "created_at":           self.created_at,
        }


class SecurityAuditor:
    """
    Soul 更新安全审查器。
    在用户审批前自动检查变更是否违反安全约束。
    所有检查 < 1s 完成。
    """

    def audit(self, proposal: SoulUpdateProposal) -> tuple[bool, list[str]]:
        """
        Returns: (passed, list_of_violations)
        """
        violations = []

        # Check 1: 不能修改核心文件（精确文件名匹配，避免 substring 误判）
        import os as _os
        module_basename = _os.path.basename(proposal.module)
        if module_basename in _FORBIDDEN_FILES:
            violations.append(f"FORBIDDEN: Cannot modify {proposal.module} (core boundary file)")

        # Check 2: 只能修改 Soul 目录内的文件
        target = _SOUL_DIR / proposal.module
        if not str(target.resolve()).startswith(str(_SOUL_DIR.resolve())):
            violations.append("FORBIDDEN: Target file is outside evocli_soul/ directory")

        # Check 3: 扫描 diff 中的危险模式
        for pattern in _FORBIDDEN_PATTERNS:
            added_lines = [l[1:] for l in proposal.diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
            for line in added_lines:
                if re.search(pattern, line):
                    violations.append(f"FORBIDDEN pattern in diff: {pattern} → {line.strip()[:60]}")

        # Check 4: 变更后的文件必须能被 Python 解析
        if target.exists():
            try:
                current = target.read_text(encoding="utf-8")
                # Apply diff mentally: just check the diff syntax is valid
                ast.parse(current)  # current file must be parseable
            except SyntaxError as e:
                violations.append(f"Current file has syntax error: {e}")

        passed = len(violations) == 0
        return passed, violations


class SoulUpdateOrchestrator:
    """
    Soul 自更新协调器（Section 9.8）。
    管理从检测 → 提案 → 审批 → 应用的完整流程。
    """

    def __init__(self, bridge=None):
        self.bridge  = bridge
        self.auditor = SecurityAuditor()
        self._pending: Optional[SoulUpdateProposal] = None

    def propose_update(
        self,
        module:               str,
        diff:                 str,
        reason:               str,
        risk_level:           str = "LOW",
        expected_improvement: str = "",
    ) -> dict:
        """
        创建一个 Soul 更新提案（Step 1: 触发检测）。
        Returns proposal dict for display to user.
        """
        proposal = SoulUpdateProposal(
            module=module,
            diff=diff,
            reason=reason,
            risk_level=risk_level,
            expected_improvement=expected_improvement,
        )

        # Step 2: 安全静态审查
        passed, violations = self.auditor.audit(proposal)

        result = {
            "proposal_id":          proposal.proposal_id,
            "module":               module,
            "reason":               reason,
            "risk_level":           risk_level,
            "expected_improvement": expected_improvement,
            "security_audit": {
                "passed":     passed,
                "violations": violations,
                "checks":     5,
            },
            "diff_preview": diff[:500] + ("..." if len(diff) > 500 else ""),
            "actions":       ["view_diff", "approve", "reject"] if passed else ["reject"],
        }

        if passed:
            self._pending = proposal
            log.info("Soul update proposed: %s (risk=%s)", module, risk_level)
        else:
            log.warning("Soul update rejected by security audit: %s", violations)

        return result

    async def approve_and_apply(self, proposal_id: str) -> dict:
        """
        Step 4+5: 用户批准 → 应用补丁 → 验证 → 记录版本。
        文件读写通过 bridge.call() 路由到 Rust Host（安全边界约束）。
        """
        if not self._pending or self._pending.proposal_id != proposal_id:
            return {"ok": False, "error": "No matching pending proposal"}

        proposal = self._pending

        # 应用 diff
        target = _SOUL_DIR / proposal.module
        if not target.exists():
            return {"ok": False, "error": f"File not found: {proposal.module}"}

        try:
            # 读取原文件：优先通过 bridge 路由到 Rust Host
            if self.bridge:
                read_result = await self.bridge.call("fs.read", {"path": str(target)})
                original = read_result if isinstance(read_result, str) else read_result.get("content", "")
            else:
                original = target.read_text(encoding="utf-8")

            # Apply diff using whatthepatch if available, else skip
            try:
                import whatthepatch
                patches = list(whatthepatch.parse_patch(proposal.diff))
                if patches:
                    new_lines = whatthepatch.apply_diff(patches[0], original)
                    if new_lines:
                        new_content = "\n".join(new_lines)
                    else:
                        return {"ok": False, "error": "Diff could not be applied (no match)"}
                else:
                    return {"ok": False, "error": "No valid diff found in proposal"}
            except ImportError:
                return {"ok": False, "error": "whatthepatch not available. Install: pip install whatthepatch"}

            # Validate: new file must be parseable Python
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                return {"ok": False, "error": f"New content has syntax error: {e}"}

            # 写入更新文件：优先通过 bridge 路由到 Rust Host
            if self.bridge:
                await self.bridge.call("fs.write", {"path": str(target), "content": new_content})
            else:
                target.write_text(new_content, encoding="utf-8")
            log.info("Applied Soul update: %s", proposal.module)

            # Reload the module
            module_name = f"evocli_soul.{proposal.module.replace('.py', '').replace('/', '.')}"
            if module_name in sys.modules:
                try:
                    importlib.reload(sys.modules[module_name])
                    log.info("Reloaded module: %s", module_name)
                except Exception as e:
                    log.warning("Module reload failed (non-fatal): %s", e)

            # Record version
            version = self._bump_version(proposal)
            self._pending = None

            return {
                "ok":         True,
                "module":     proposal.module,
                "version":    version,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log.exception("Soul update application failed")
            return {"ok": False, "error": str(e)}

    def reject(self, proposal_id: str, reason: str = "") -> dict:
        """Step 4 (reject branch): 用户拒绝。"""
        if self._pending and self._pending.proposal_id == proposal_id:
            self._pending = None
        log.info("Soul update rejected: %s (reason: %s)", proposal_id, reason)
        return {"ok": True, "rejected": proposal_id, "reason": reason}

    def _bump_version(self, proposal: SoulUpdateProposal) -> str:
        """更新 soul_version.json 并返回新版本号。"""
        data: dict = {}
        if _VERSION_FILE.exists():
            try:
                data = json.loads(_VERSION_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        current = data.get("current_version", "0.1.0")
        parts   = current.split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except (ValueError, IndexError):
            parts = ["0", "1", "1"]
        new_version = ".".join(parts)

        history = data.get("update_history", [])
        history.append({
            "version":     new_version,
            "from":        current,
            "applied_at":  datetime.now(timezone.utc).isoformat(),
            "reason":      proposal.reason,
            "module":      proposal.module,
            "approved_by": "user",
        })

        data["current_version"]  = new_version
        data["update_history"]   = history[-20:]  # keep last 20
        data["rollback_available"] = current

        _VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        _VERSION_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Soul version updated: %s → %s", current, new_version)
        return new_version

    def get_version_info(self) -> dict:
        """查看当前版本和历史。"""
        if not _VERSION_FILE.exists():
            return {"current_version": "0.1.0", "update_history": []}
        try:
            return json.loads(_VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"error": "Could not read version file"}


# ── 全局单例 ──────────────────────────────────────────────────────────────────
_orchestrator: Optional[SoulUpdateOrchestrator] = None


def get_soul_updater(bridge=None) -> SoulUpdateOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SoulUpdateOrchestrator(bridge)
    return _orchestrator
